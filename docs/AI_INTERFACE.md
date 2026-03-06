# MasterControl - Interface IA (chat no terminal)

## Objetivo

Simplificar a interacao com o MasterControl sem precisar lembrar combinacoes longas de flags.

## Como iniciar

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai
```

Comando unico (sem entrar no REPL):

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai --once "restart nginx service"
```

## Fluxo de uso

1. Digite o comando natural (ex.: `restart nginx service`).
2. A interface mostra:
   - mensagem humanizada,
   - path escolhido,
   - intent cluster,
   - acao mapeada,
   - outcome.
3. Se houver acao mapeada:
   - modo `confirm`: pergunta `nao / dry-run / executar`.
   - modo `dry-run`: executa dry-run automaticamente.
   - modo `execute`: executa automaticamente (alto risco pede confirmacao textual `EXECUTAR`).
   - modo `plan`: somente analise (sem executar).

## Comandos da interface

- `/help`
- `/status`
- `/risk <low|medium|high|critical>`
- `/path <auto|fast|deep|fast_with_confirm>`
- `/mode <confirm|plan|dry-run|execute>`
- `/incident <on|off>`
- `/operator <nome>`
- `/quit`

## Observacoes de seguranca

- A interface respeita os mesmos guardrails do runtime:
  - confirmacao para `fast_with_confirm`,
  - bloqueio/passo explicito para alto risco,
  - allowlist privilegiada confiavel em `/etc/mastercontrol`.

