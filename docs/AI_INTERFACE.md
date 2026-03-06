# MasterControl - Interface IA (chat no terminal)

## Objetivo

Simplificar a interacao com o MasterControl sem precisar lembrar combinacoes longas de flags, com suporte opcional a modelo local via Ollama.

## Dependencias para modo LLM

Modelos recomendados no host atual:

```bash
ollama pull qwen3.5:4b
ollama pull qwen2.5:7b
```

Recomendacao para uso conversacional:

- `ollama` como runtime local
- `qwen3.5:4b` para resposta mais natural (com `--llm-timeout 45`)
- `qwen2.5:7b` para menor latencia

Se o modelo/runtime falhar, a interface entra automaticamente em fallback local (sem LLM), mantendo o fluxo deterministico do runtime.
No adapter atual, `mc-ai` tenta `--think=false` por padrao para priorizar resposta conversacional com menor latencia (com fallback automatico sem essa flag em runtimes antigos).
`qwen3.5:4b` requer Ollama `>= 0.17.1`.

## Como iniciar

Atalho conversacional recomendado (tenta runtime local atualizado automaticamente; usa `qwen3.5:4b` com timeout maior quando disponivel):

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

- modelo: `qwen3.5:4b`
- timeout: `45s`
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
/home/irving/ruas/repos/master-control/scripts/mc-ai --llm-model qwen3.5:4b --llm-timeout 45
```

Perfil de menor latencia:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai --llm-model qwen2.5:7b --llm-timeout 25
```

## Fluxo de uso

1. Digite o comando natural (ex.: `restart nginx service`).
2. Se LLM estiver ativo:
   - o modelo classifica entrada como `intent` ou `chat`,
   - em `intent`, pode normalizar o texto para melhorar mapeamento,
   - em `chat`, responde no terminal sem acionar execucao.
3. A interface mostra:
   - mensagem humanizada,
   - path escolhido,
   - intent cluster,
   - acao mapeada,
   - outcome.
4. Se houver acao mapeada:
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
