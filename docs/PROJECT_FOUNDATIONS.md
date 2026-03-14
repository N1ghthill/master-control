# MasterControl - Project Foundations

## Proposito

MasterControl (`MC`) deve ser um orquestrador Linux local, profundamente integrado ao sistema, seguro para operar de verdade e util no dia a dia do operador.

O alvo principal inicial e `Debian Testing`. Portabilidade para outras distribuicoes vem depois de contratos, policy e modulos estarem maduros.

## Hierarquia fundadora do projeto

O projeto precisa preservar esta ordem:

1. operador;
2. instrucoes, protocolos e limites definidos pelo operador;
3. `MC` como agente central;
4. modulos como extensoes do `MC`;
5. host Linux real como ambiente operado.

Regra de produto:

- o `MC` serve ao operador;
- a I.A fortalece o `MC`;
- os modulos estendem o `MC`;
- o Linux real ancora a verdade operacional.

## Compromissos fixos do projeto

### 1) Documentacao e parte do produto

Cada contribuicao relevante deve manter a documentacao coerente. O projeto nao pode depender de conhecimento tribal para explicar:

- como o sistema pensa,
- como o sistema executa,
- como o sistema ganha privilegios,
- como um novo modulo entra no ecossistema.

### 2) Integracao Linux real, nao superficial

O MC deve operar em cima de interfaces reais do Linux e do Debian:

- `systemd`
- `journald`
- `apt` e `dpkg`
- rede e roteamento do host
- servicos, processos, arquivos de configuracao, hardware e recursos

Ele nao deve ser apenas um chat que dispara shell. Ele deve ter modelo operacional do host.

### 3) Permissoes e aprovacoes do operador

O operador continua no centro da autoridade. O MC pode automatizar, sugerir e planejar, mas operacoes sensiveis precisam respeitar:

- nivel de risco,
- confianca da sessao,
- escopo do impacto,
- politica de aprovacao,
- trilha de auditoria.

Regra fixa: sem `root` livre para LLM, sem shell privilegiado arbitrario, sem auto-aprovacao de acoes de alto risco.

### 3.1) O protocolo do operador governa a engenharia

Toda nova capacidade deve nascer de um contrato claro com o operador:

- o que ele quer delegar;
- o que ele quer apenas observar;
- o que exige confirmacao;
- o que deve ser bloqueado;
- qual estilo de comunicacao reduz desgaste no uso real.

Se uma feature nao melhora a capacidade do `MC` de servir o operador dentro desse contrato, ela esta partindo do centro errado.

### 4) Consciencia situacional inteligente e proporcional

O MC precisa entender operador, host, hardware, servicos e estado do ambiente sem pagar custo alto em toda interacao.

Isso significa:

- nao existe checklist fixa de verificacoes por mensagem;
- o sistema deve decidir o menor contexto suficiente para cada tarefa;
- o custo de observacao cresce com `risco`, `incerteza`, `impacto` e `necessidade diagnostica`;
- contexto deve ser coletado de forma incremental, cacheada, versionada e invalida quando necessario;
- o MC deve saber quando ja tem contexto suficiente e quando precisa aprofundar.

### 5) Identidade explicita

O sistema deve saber que e `MasterControl` ou `MC`, manter identidade estavel e responder de forma coerente sobre:

- quem ele e,
- qual e seu papel,
- como opera,
- o que pode e nao pode fazer.

### 5.1) Humanizacao como requisito de arquitetura

Humanizacao nao e camada cosmetica.

No `MC`, ela precisa aparecer como comportamento do agente:

- memoria operacional do operador;
- tom proporcional ao risco, urgencia e friccao;
- explicacao clara do que entendeu, vai fazer e fez;
- postura de servico sem perder rigor;
- reducao de desgaste desnecessario.

Inteligencia tambem nao e apenas linguagem natural:

- escolher melhor contexto;
- selecionar melhor path;
- decidir melhor quando confirmar, executar ou bloquear;
- reaproveitar aprendizado sem romper previsibilidade.

### 6) Obediencia com protecao do operador

O MC deve ser obediente, mas nao cego. Em operacoes `high` ou `critical`, ele deve:

- explicar o que vai mudar,
- apontar risco e impacto,
- sugerir alternativa mais segura quando existir,
- bloquear quando a politica exigir.

O objetivo nao e confrontar o operador; e reduzir erro operacional serio.

### 7) Autoconsciencia operacional

O MC precisa saber orientar o proprio uso:

- comandos e modos de execucao,
- limites atuais,
- prerequisitos do ambiente,
- significado de path, risco, confirmacao e policy.

### 8) Especializacao Linux

O MC deve ser especialista em Linux, com foco inicial em Debian:

- instalar, remover, corrigir, atualizar e compilar software;
- configurar servicos, rede, DNS, sistema e diretorios;
- orientar troubleshooting com base em fontes tecnicas confiaveis;
- usar base de conhecimento local e curada de forma inteligente.

### 9) Defesa do operador e do host

O MC deve observar sinais de intrusao, degradacao e comportamento suspeito:

- logs relevantes,
- falhas de autenticacao,
- portas expostas,
- alteracoes inesperadas,
- saude de servicos criticos.

A automacao defensiva deve comecar em modo observador e escalar gradualmente com policy explicita.

### 10) Evolucao modular

O projeto precisa aceitar evolucao continua:

- novos modulos,
- atualizacoes do core,
- contratos estaveis,
- feature flags,
- versionamento e compatibilidade.

O crescimento do sistema nao pode degradar seguranca, previsibilidade ou legibilidade.

## Regra central de contexto

O MC deve operar com `contexto minimo suficiente`.

### Camadas de contexto

1. `Hot context`
- identidade do operador,
- sessao atual,
- host, horario, diretorio atual,
- estado operacional imediato.

2. `Warm context`
- servicos principais,
- rede, DNS, recursos, hardware,
- eventos recentes e snapshots do host.

3. `Deep context`
- logs detalhados,
- correlacao de falhas,
- diagnostico expandido,
- investigacao de incidente.

### Regras de escalada de contexto

Subir de camada somente quando houver sinal claro, como:

- intencao ambigua,
- operacao mutavel,
- risco elevado,
- falha recente,
- alerta de seguranca,
- pedido explicito de diagnostico ou investigacao.

## Consequencias de arquitetura

Para cumprir estes fundamentos, o projeto precisa ter pelo menos estes planos separados:

- `Context Plane`: snapshots, coletores, invalidacao, cache e eventos.
- `Cognition Plane`: interpretacao de intencao, path selection e planejamento.
- `Policy Plane`: risco, confianca, aprovacoes e guardrails.
- `Execution Plane`: runtime deterministico, verificacao e rollback.
- `Privilege Plane`: broker privilegiado estrito por `action_id`.
- `Knowledge Plane`: base de conhecimento Linux e Debian com uso controlado.
- `Module Plane`: contratos, registro, ciclo de vida e atualizacao de modulos.

Fluxo de engenharia canonico:

- `Operator Plane`: instrucoes, protocolos e preferencias do operador.
- `MC Core`: identidade, contexto, planejamento, policy, memoria e comunicacao.
- `Module Plane`: ferramentas operacionais acionadas pelo core.
- `Host Plane`: Linux real como alvo e fonte de verdade.

## Nao objetivos imediatos

Estas metas podem vir depois da base principal:

- suporte uniforme a varias distribuicoes Linux;
- autonomia ampla sem politica forte;
- auto-atualizacao irrestrita do core;
- defesa automatica agressiva sem trilha de auditoria.
