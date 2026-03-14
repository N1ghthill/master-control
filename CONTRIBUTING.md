# Contributing to MasterControl

Este repositorio ainda esta em consolidacao. Quem contribuir deve preservar clareza de arquitetura, seguranca e integracao Linux real.

## Leitura minima antes de codar

Leia nesta ordem:

1. `README.md`
2. `docs/INDEX.md`
3. `docs/PROJECT_FOUNDATIONS.md`
4. `docs/MC_ENGINEERING_FLOW.md`
5. `docs/ARCHITECTURE.md`
6. `docs/ROADMAP.md`
7. `docs/CODE_MAP.md`

## Regras que nao podem ser quebradas

- Nao dar `root` livre ao LLM.
- Nao criar execucao privilegiada fora de `action_id` allowlisted.
- Nao transformar cada interacao em uma bateria fixa de verificacoes do host.
- Nao sacrificar auditoria para ganhar conveniencia.
- Nao otimizar para multiplas distros antes de estabilizar `Debian Testing`.
- Nao inverter a hierarquia `operador -> MC -> modulos -> host`.
- Nao tratar humanizacao e inteligencia como acessorios de interface.

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

## Templates de trabalho

Use os templates do repositorio para manter o eixo `operator-first` e `MC-first`:

- `.github/ISSUE_TEMPLATE/mc_capability.md`
- `.github/ISSUE_TEMPLATE/mc_regression.md`
- `.github/PULL_REQUEST_TEMPLATE.md`

Eles existem para forcar o mesmo fluxo de engenharia definido em `docs/MC_ENGINEERING_FLOW.md`.

## Como pensar mudancas

Ao propor ou implementar qualquer mudanca, responda internamente a estas perguntas:

1. Isso serve melhor o operador ou so adiciona complexidade tecnica?
2. Isso fortalece o `MC` como agente central ou espalha logica por modulos/ferramentas?
3. Isso melhora ou piora a seguranca operacional?
4. Isso aumenta ou reduz a integracao real com Linux?
5. Isso respeita o principio de `contexto minimo suficiente`?
6. Isso cria uma API ou contrato que outros modulos conseguirao manter?
7. Isso esta documentado no lugar certo?

## Fluxo de engenharia obrigatorio

Projete mudancas nesta ordem:

1. necessidade do operador;
2. capacidade do `MC`;
3. contrato;
4. policy e seguranca;
5. integracao de modulo;
6. humanizacao e inteligencia;
7. testes e smoke;
8. documentacao.

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

Em termos de centro de gravidade:

- primeiro o `MC`,
- depois os modulos,
- nunca o contrario.

Se a mudanca tocar privilegios, contexto, seguranca ou autonomia, trate a revisao como mudanca critica.
