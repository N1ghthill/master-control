# MasterControl - Identidade, confianca e obediencia

## Objetivo

Garantir que o agente seja:

- prestativo no uso diario,
- obediente ao operador dono,
- resistente a uso indevido.

## 1) "Quem sou eu?" no contexto do agente

MasterControl identifica o operador por sinais combinados, nao por um unico fator:

- usuario local Unix e grupos,
- continuidade de sessao,
- contexto de host esperado,
- historico recente de acoes aprovadas,
- horario/padrao operacional.

Isso gera um `trust score` dinamico por sessao.

## 2) Obediencia com fronteiras

Obediencia nao significa executar tudo cegamente. Significa:

1. interpretar corretamente a intencao;
2. executar quando politica permitir;
3. pedir confirmacao quando risco exigir;
4. bloquear e explicar quando for inseguro.

## 3) Matriz de risco x confianca

- `Baixo risco + alta confianca`: auto-execucao.
- `Medio risco + media confianca`: confirmacao curta.
- `Alto risco + baixa/media confianca`: step-up obrigatorio.
- `Critico`: step-up forte + janela curta + auditoria reforcada.

## 4) Step-up amigavel (sem UX robotica)

- Confirmacao contextual em linguagem natural:
  - o que vai mudar,
  - impacto esperado,
  - como desfazer.
- Tokens de aprovacao com validade curta para lote relacionado.

## 5) Anti-abuso

- Limite de escopo por comando (blast radius).
- Rate limit para acoes sensiveis.
- "two-man rule" opcional para operacoes destrutivas.
- Kill-switch local (`mastercontrol pause`).

## 6) Memoria de relacionamento

Memoria permitida:

- preferencias de estilo e fluxo,
- alias de comandos frequentes,
- padroes de aprovacao do operador.

Memoria proibida:

- escalacao automatica de privilegio fora de policy,
- auto-remocao de guardrails,
- auto-aprovacao de risco alto.

