# Contributing to MasterControl

Este repositorio ainda esta em consolidacao. Quem contribuir deve preservar clareza de arquitetura, seguranca e integracao Linux real.

## Leitura minima antes de codar

Leia nesta ordem:

1. `README.md`
2. `docs/INDEX.md`
3. `docs/PROJECT_FOUNDATIONS.md`
4. `docs/ARCHITECTURE.md`
5. `docs/ROADMAP.md`
6. `docs/CODE_MAP.md`

## Regras que nao podem ser quebradas

- Nao dar `root` livre ao LLM.
- Nao criar execucao privilegiada fora de `action_id` allowlisted.
- Nao transformar cada interacao em uma bateria fixa de verificacoes do host.
- Nao sacrificar auditoria para ganhar conveniencia.
- Nao otimizar para multiplas distros antes de estabilizar `Debian Testing`.

## Stack e alvo atual

- Linguagem principal: `Python 3`.
- Alvo principal: `Debian Testing`.
- Interface local: `scripts/mastercontrol`, `scripts/mc-ai`, `scripts/mc-ai-chat`.
- Runtime privilegiado atual: `mastercontrol/runtime/root_exec.py`.

## Dependencias e reproducao

O repositorio ainda precisa de um manifesto formal de dependencias.

Hoje, os testes que carregam o kernel de humanizacao dependem de `PyYAML`.

Suite atual:

```bash
python3 mastercontrol/interface/flow_smoke.py --verbose
python3 -m unittest discover -s tests -v
```

O CI executa exatamente essa sequencia: primeiro smoke do fluxo real da interface, depois a suite completa.

## Como pensar mudancas

Ao propor ou implementar qualquer mudanca, responda internamente a estas perguntas:

1. Isso melhora ou piora a seguranca operacional?
2. Isso aumenta ou reduz a integracao real com Linux?
3. Isso respeita o principio de `contexto minimo suficiente`?
4. Isso cria uma API ou contrato que outros modulos conseguirao manter?
5. Isso esta documentado no lugar certo?

## Quando alterar documentacao

Atualize documentacao junto com codigo quando houver mudanca em:

- arquitetura,
- comportamento de risco ou policy,
- fluxo privilegiado,
- novos modulos ou novas capacidades,
- comportamento da interface do operador.

## Quando alterar testes

Adicione ou ajuste testes sempre que mudar:

- parse de intents,
- resolucao de modulos,
- policy de risco,
- execucao privilegiada,
- comportamento de contexto e roteamento `fast/deep`.

## Estrategia de contribuicao

Prefira mudancas pequenas e verificaveis:

- primeiro contratos,
- depois implementacao,
- depois testes,
- depois docs complementares.

Se a mudanca tocar privilegios, contexto, seguranca ou autonomia, trate a revisao como mudanca critica.
