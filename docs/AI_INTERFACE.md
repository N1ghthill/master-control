# MasterControl - Interface IA (chat no terminal)

## Objetivo

Simplificar a interacao com o MasterControl sem precisar lembrar combinacoes longas de flags, com suporte opcional a modelo local via Ollama.

## Dependencias para modo LLM

Modelos recomendados no host atual:

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
ollama pull qwen2.5:7b
```

Recomendacao para uso conversacional:

- `ollama` como runtime local
- `qwen3:4b-instruct-2507-q4_K_M` como padrao (modelo menor, rapido e bom em PT-BR)
- `qwen2.5:7b` como alternativa de fallback com boa estabilidade de rota

Se o modelo/runtime falhar, a interface entra automaticamente em fallback local (sem LLM), mantendo o fluxo deterministico do runtime.
No adapter atual, `mc-ai` tenta `--think=false` por padrao para priorizar resposta conversacional com menor latencia (com fallback automatico sem essa flag em runtimes antigos).
Modelos `qwen3` tambem exigem runtime Ollama recente.

## Como iniciar

Atalho conversacional recomendado (tenta runtime local atualizado automaticamente):

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai-chat
```

Comando global no terminal:

```bash
mastercontrol
```

Sem argumentos em terminal interativo, `mastercontrol` abre a UI de terminal (TUI) com layout continuo.
Para forcar o REPL classico:

```bash
mastercontrol --repl
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

- modelo: `qwen3:4b-instruct-2507-q4_K_M`
- timeout: `25s`
- autodetecta `~/.local/ollama-latest/bin/ollama` e usa `OLLAMA_HOST=127.0.0.1:11435` quando disponivel
- no modo interativo, faz warm-up automatico do LLM na abertura para reduzir latencia da primeira resposta
- quando chamado sem argumentos, abre a TUI por padrao

Comando unico (sem entrar no REPL):

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai --once "restart nginx service"
```

Desabilitar LLM:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai --no-llm
```

Desabilitar warm-up automatico (somente modo interativo):

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai --no-llm-warmup
```

Trocar modelo:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai --llm-model qwen3:4b-instruct-2507-q4_K_M --llm-timeout 25
```

Perfil alternativo com fallback estavel:

```bash
/home/irving/ruas/repos/master-control/scripts/mc-ai --llm-model qwen2.5:7b --llm-timeout 25
```

## Fluxo ponta a ponta

1. Voce envia uma entrada no `mc-ai`:
   - exemplo conversacional: `como voce esta?`
   - exemplo operacional: `restart nginx service`
   - no REPL, warm-up inicial do modelo ocorre automaticamente antes da primeira mensagem
2. O adapter LLM tenta interpretar a entrada:
   - classifica como `chat` ou `intent`
   - em `intent`, pode normalizar texto para melhorar mapeamento
   - comandos operacionais explicitos (`apt ...`, `ping ...`, etc.) mantem intent original (bypass de normalizacao)
   - se o LLM responder `chat` para texto operacional, guardrail local força `intent`
   - se a normalizacao perder alvo/escopo (IP, dominio, `bogus`, etc.), guardrail preserva o texto original
   - em erro/timeout do LLM, entra fallback local deterministico
3. Se for `chat`:
   - a interface responde no terminal com `[ai] ...`
   - perguntas de identidade/localizacao usam guardrail local (perfil da alma + contexto real do host)
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

- `mastercontrol` (TUI por padrao)
- `mastercontrol --repl` (REPL classico)
- `mastercontrol --tui` (forca TUI)
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
- A identidade de resposta em `chat` eh ancorada no perfil local (`MasterControl`, creator `Irving`) para evitar autoidentificacao incorreta do modelo.
- Guardrails operacionais reduzem misroute de `intent` para `chat` e evitam perda de contexto na normalizacao de comandos.

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
