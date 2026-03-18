# Providers

## Current providers

Master Control currently supports these planning providers:

- `auto`: prefer local Ollama, then OpenAI, then the local heuristic planner
- `openai`: use the OpenAI Responses API explicitly
- `ollama`: use the Ollama `/api/chat` endpoint with schema-constrained JSON output
- `heuristic`: local rules-only planner for offline bootstrap and tests
- `noop`: disabled provider that only returns static guidance

## OpenAI provider

The OpenAI integration uses the `Responses API` with a single required function tool named `submit_plan`.

Why this shape:

- the model returns a structured plan instead of free-form reasoning
- the plan is restricted to the currently registered MC tools
- execution still happens inside MC, through policy and audit

## Ollama provider

The Ollama integration uses the `/api/chat` endpoint with a strict JSON schema in the `format` field.

Why this shape:

- the local model stays on the same planning contract as the other providers
- planning remains structured even without remote function-calling infrastructure
- execution still happens inside MC, through policy and audit

`mc doctor` probes the local Ollama endpoint through `/api/tags` and reports whether the configured model is already installed. This is also what drives `MC_PROVIDER=auto`.

## Multi-turn context

MC persists provider state per chat session. For providers that support it, the active session can store the last provider response id and reuse it on the next turn.

For OpenAI, this means the app can pass `previous_response_id` when the same session is resumed.

MC also persists recent conversation messages locally and passes them back to the provider when no remote response chain is available. This keeps follow-up requests useful across local and remote providers.

To avoid depending only on a short message window, MC also maintains a compact deterministic session summary with tracked entities and recent findings, such as:

- tracked unit or service
- tracked filesystem path
- last intent
- recent memory, disk, service, log, and process observations

That same summary is also used to derive proactive suggestions and alerts per session, which can be shown directly in chat responses or inspected via the CLI.

MC also persists session-scoped observations with TTL metadata. Before each planning pass, the app computes freshness for the latest host observations and passes that to the active provider. This gives all planners the same rule:

- fresh observations may be summarized and reused
- stale observations should be refreshed through the matching typed tool before the planner relies on them

The local heuristic planner already uses this actively for performance diagnosis, so repeated requests such as `o host esta lento` can refresh memory, processes, or service state when the previous observation window expired.

Operators can inspect the same freshness state directly through:

- `mc observations --session-id <id>`
- `mc observations --session-id <id> --stale-only`

MC also persists those suggestions as explicit session recommendations, so follow-up operations can track recommendation lifecycle instead of recomputing meaning from raw chat alone.

When a recommendation includes an executable action, that action remains provider-independent metadata. The provider proposes observations and plans; MC decides whether a recommendation can expose a typed action such as `restart_service`, and any execution still goes through local policy, confirmation, and audit.

The local heuristic provider also supports a small set of approval-gated actions directly, such as `restart_service`, `reload_service`, and safe reads of managed config paths. Those plans still execute through the same local confirmation boundary as every other tool.

The app can also call a provider multiple times inside one user turn. Earlier tool results are summarized back into the planning context so the next planning pass can continue the diagnosis or stop and summarize.

## Environment variables

Core selection:

- `MC_PROVIDER=auto|openai|ollama|heuristic|noop`
- `MC_PROVIDER_PROBE_TIMEOUT_S` defaults to `0.75`

OpenAI credentials and endpoint:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL` defaults to `https://api.openai.com/v1`
- `OPENAI_ORGANIZATION` optional
- `OPENAI_PROJECT` optional

OpenAI behavior:

- `MC_OPENAI_MODEL` defaults to `gpt-5.4`
- `MC_OPENAI_REASONING_EFFORT` defaults to `none`
- `MC_OPENAI_TIMEOUT_S` defaults to `20`
- `MC_OPENAI_STORE` defaults to `false`

Ollama behavior:

- `MC_OLLAMA_BASE_URL` defaults to `http://localhost:11434/api`
- `MC_OLLAMA_MODEL` defaults to `qwen2.5:7b`
- `MC_OLLAMA_TIMEOUT_S` defaults to `60`
- `MC_OLLAMA_KEEP_ALIVE` optional
- `OLLAMA_API_KEY` optional

## Recommended startup

```bash
export OPENAI_API_KEY=...
export MC_PROVIDER=openai
mc doctor
mc chat --new-session --once "o host esta lento"
mc sessions --limit 5
mc chat --session-id 1 --once "e agora me mostre a memoria"
```

If you want automatic local fallback when no key is configured:

```bash
export MC_PROVIDER=auto
mc doctor
```

When `MC_PROVIDER=auto`, MC resolves the backend in this order:

1. `ollama` if the local endpoint is reachable and the configured model is installed
2. `openai` if `OPENAI_API_KEY` is configured
3. `heuristic` otherwise

Direct local planning with Ollama:

```bash
ollama serve
ollama pull qwen2.5:7b
export MC_PROVIDER=ollama
export MC_OLLAMA_MODEL=qwen2.5:7b
mc doctor
mc chat --once "o host esta lento"
```

If the local server is listening on a different port or host, point MC to it explicitly:

```bash
export MC_PROVIDER=ollama
export MC_OLLAMA_BASE_URL=http://127.0.0.1:11435/api
export MC_OLLAMA_MODEL=qwen2.5:7b
mc doctor
mc chat --once "mostre o uso de memoria"
```

One operational finding from the current alpha work: MC's Ollama integration has now been validated against a real local endpoint and installed model inventory, not only mocked transports. The current alpha default is `qwen2.5:7b`, but validated host setups can still override it through `MC_OLLAMA_MODEL`.
