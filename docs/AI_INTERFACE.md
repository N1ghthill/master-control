# MasterControl - Interface IA (chat no terminal)

## Objetivo

Simplificar a interacao com o MasterControl sem precisar lembrar combinacoes longas de flags, com suporte opcional a modelo local via Ollama.

## Dependencias para modo LLM

Modelos recomendados no host atual:

```bash
ollama pull qwen2.5:7b
ollama pull qwen3.5:4b
```

Recomendacao para uso conversacional:

- `ollama` como runtime local
- `qwen2.5:7b` como padrao para conversa com latencia mais baixa e roteamento mais estavel
- `qwen3.5:4b` como opcao para estilo mais elaborado (latencia maior)

Se o modelo/runtime falhar, a interface entra automaticamente em fallback local (sem LLM), mantendo o fluxo deterministico do runtime.
No adapter atual, `mc-ai` tenta `--think=false` por padrao para priorizar resposta conversacional com menor latencia (com fallback automatico sem essa flag em runtimes antigos).
`qwen3.5:4b` requer Ollama `>= 0.17.1`.

## Como iniciar

Atalho conversacional recomendado (tenta runtime local atualizado automaticamente):

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai-chat
```

Se o runtime local atualizado nao estiver rodando, iniciar:

```bash
/home/irving/.local/ollama-latest/bin/ollama serve
```

Entrada padrao da interface (sem preset conversacional):

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai
```

Padrao atual do `mc-ai`:

- modelo: `qwen2.5:7b`
- timeout: `25s`
- autodetecta `~/.local/ollama-latest/bin/ollama` e usa `OLLAMA_HOST=127.0.0.1:11435` quando disponivel

Comando unico (sem entrar no REPL):

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai --once "restart nginx service"
```

Desabilitar LLM:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai --no-llm
```

Trocar modelo:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai --llm-model qwen2.5:7b --llm-timeout 25
```

Perfil de resposta mais elaborada (maior latencia):

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai --llm-model qwen3.5:4b --llm-timeout 45
```

## Fluxo ponta a ponta

1. Voce envia uma entrada no `mc-ai`:
   - exemplo conversacional: `como voce esta?`
   - exemplo operacional: `restart nginx service`
2. O adapter LLM tenta interpretar a entrada:
   - classifica como `chat` ou `intent`
   - em `intent`, pode normalizar texto para melhorar mapeamento
   - em erro/timeout do LLM, entra fallback local deterministico
3. Se for `chat`:
   - a interface responde no terminal com `[ai] ...`
   - nao aciona execucao operacional
4. Se for `intent`:
   - o `mastercontrold` roda analise de tom/contexto
   - escolhe `path` (`fast`, `deep`, `fast_with_confirm`)
   - tenta mapear para `action_id` allowlisted
   - monta plano, risco, outcome e next step
5. Quando existe acao mapeada, o comportamento depende do modo:
   - `plan`: so analise (nao executa)
   - `confirm`: pergunta `nao / dry-run / executar`
   - `dry-run`: valida sem mutar sistema
   - `execute`: executa (alto risco exige confirmar `EXECUTAR`)
6. Toda mutacao real passa pelos guardrails:
   - policy de risco + confirmacoes
   - execucao privilegiada via allowlist confiavel
   - trilha de auditoria com `request_id`

## Comandos da interface

- `/help`
- `/status`
- `/risk <low|medium|high|critical>`
- `/path <auto|fast|deep|fast_with_confirm>`
- `/mode <confirm|plan|dry-run|execute>`
- `/incident <on|off>`
- `/operator <nome>`
- `/llm <on|off|status>`
- `/model <nome>`
- `/raw <comando natural>` (bypass do LLM para um comando)
- `/quit`

## Observacoes de seguranca

- A interface respeita os mesmos guardrails do runtime:
  - confirmacao para `fast_with_confirm`,
  - bloqueio/passo explicito para alto risco,
  - allowlist privilegiada confiavel em `/etc/mastercontrol`.
- O LLM nao executa comandos do sistema e nao substitui as validacoes do runtime.

## Roteiro diario (5 comandos)

1. Validar servico LLM local:

```bash
systemctl --user status ollama-local.service --no-pager
```

2. Iniciar interface no perfil padrao:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai
```

3. Conversar sem executar nada:

```text
/mode plan
```

4. Testar uma intencao operacional com seguranca:

```text
restart nginx service
```

na pergunta de execucao, escolher `d` (dry-run).

5. Ver estado atual da sessao:

```text
/status
```
