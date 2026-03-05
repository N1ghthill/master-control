# MasterControl - Inteligencia Operacional

## Proposito

Fazer o MasterControl operar como orquestrador real do Debian:

- entender contexto dinamico do host,
- decidir com autonomia o nivel de raciocinio necessario,
- executar com seguranca e verificacao.

## 1) Integracao profunda (camadas)

1. Camada de contexto (`mc-contextd`)
- Coleta continua de sessao, rede, servicos, seguranca e recursos.

2. Camada cognitiva (`Path Selector` + planner)
- Decide `FAST`, `DEEP` ou `FAST_WITH_CONFIRM`.
- Usa risco, incerteza e estado atual do host.

3. Camada de execucao (`mc-runtime`)
- Encaminha para modulo correto e valida resultado.

4. Camada privilegiada (`Privilege Plane`)
- Executa somente `action_id` allowlisted para operacoes root.

## 2) Loop operacional

1. Observar.
2. Entender intencao.
3. Escolher caminho fast/deep.
4. Planejar.
5. Aplicar politica e confianca.
6. Executar.
7. Verificar.
8. Registrar.
9. Aprender.

## 3) Fast vs Deep: autonomia obrigatoria

Quem decide e o MasterControl, nunca o operador.

Heuristica inicial:

- `FAST`: baixa criticidade + alta confianca + baixa incerteza.
- `FAST_WITH_CONFIRM`: baixa/média complexidade com impacto relevante.
- `DEEP`: incerteza alta, operacao sensivel, host degradado, ou historico de falhas similares.

Fallback:

- se `FAST` falhar por falta de contexto -> reclassificar para `DEEP` e reaprender.

## 4) Metricas de inteligencia operacional

- p95 de latencia do plano (`FAST` e `DEEP`).
- taxa de sucesso por modulo.
- taxa de reclassificacao `FAST -> DEEP`.
- incidentes evitados por policy.
- taxa de rollback por classe de risco.

## 5) Criterio de maturidade

MasterControl so escala autonomia quando:

- acertar o roteamento fast/deep de forma consistente,
- manter auditoria completa,
- reduzir regressao operacional em cenarios reais.

