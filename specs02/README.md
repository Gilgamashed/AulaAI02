# Specs02 — Fase 2 (Portfólio)

Índice dos incrementos da fase 2 do SynapseShop. A fase 1 (curso de 25 aulas)
está encerrada e congelada na tag `apresentacao-final`; as specs que a
descrevem permanecem em [`specs/`](../specs/README.md) apenas como histórico.

A fonte ativa de requisitos é este diretório, governado pela
[meta-spec da fase 2](00_diretriz_incremental_specdd_fase2.md). O documento de
origem da nova fase é [`docs/portfolio/preparacao`](../docs/portfolio/preparacao).

## Regras rápidas

- Implemente **apenas** o incremento com status `Em andamento` ou
  `Especificado` e priorizado no backlog.
- Toda mudança exige evidência em
  [`docs/portfolio/evidencias/`](../docs/portfolio/evidencias/README.md).
- Nenhum incremento pode regredir a fase 1 (testes, cobertura, contratos,
  OpenAPI e smoke do MVP).
- Ideia nova entra no backlog; não entra no código sem spec própria.

## Incrementos

| # | Spec | Prioridade | Status |
|---|---|---|---|
| 01 | [Avaliação de IA](01_fase2_spec_avaliacao-ia.md) | P0 | Concluído |
| 02 | [Texto-para-SQL v2](02_fase2_spec_texto-para-sql-v2.md) | P0 | Especificado |

Status possíveis: `Planejado` (só backlog), `Especificado` (spec escrita e
aprovada), `Em andamento`, `Concluído`, `Descartado`.

## Baseline de IA — 2026-11-16

Golden set versão 1: **58 itens / 11 categorias**, 22 com `ci_mock`.
Baseline válido em `LLM_PROVIDER=mock`; o baseline Gemini ficou pendente
porque a chave atingiu a cota diária de **20 requisições/dia** da free tier
(HTTP 429), conforme
[nota de indisponibilidade](../docs/portfolio/evidencias/ia/2026-11-16_gemini-indisponivel.md).

| Métrica | Mock |
|---|---:|
| Taxa geral | 58,62% (34/58) |
| Gate (`consulta` + `rag_tecnico`) | 50,00% (24/48) |
| Latência p50 / p95 | 72 ms / 1.180 ms |
| Falhas | 12 `nao_suportado`, 12 `resposta_inesperada` |

Taxa por categoria (mock): `contagem` 4/6 · `listagem` 3/6 · `agregacao` 6/9 ·
`serie_temporal` 0/5 · `join` 2/6 · `jsonb_itens` 0/5 · `ranking` 3/5 ·
`fora_dominio` 4/4 · `rag_tecnico` 6/6 · `rag_fora_corpus` 3/3 · `assist` 3/3.

Evidências:
[relatório JSON](../docs/portfolio/evidencias/ia/2026-11-16_2302_mock.json) ·
[resumo Markdown](../docs/portfolio/evidencias/ia/2026-11-16_2302_mock.md).

O baseline é a linha de base da spec `02`: as categorias `serie_temporal`,
`jsonb_itens` e parte de `join` falham exatamente nos pontos descritos na spec
— validação por regex e mock sem padrões para datas/itens.

## Backlog priorizado

Prioridade é valor de portfólio × risco técnico, não esforço. O backlog é
intenção: só vira trabalho quando ganha spec numerada.

### P0 — credibilidade técnica

| Item | Por que importa | Incremento | Status |
|---|---|---|---|
| Avaliação mensurável dos três pilares de IA | Hoje a qualidade é percebida, não medida | 01 | Concluído |
| Texto-para-SQL com cobertura real de perguntas | Principal queixa de uso; validação atual gera falsos negativos | 02 | Especificado |
| Demo pública com seed e credenciais fixas | Recrutador precisa abrir e testar sem instalar nada | — | Planejado |
| README de recrutador (problema, arquitetura, trade-offs) | É a primeira coisa lida em uma triagem | — | Planejado |

### P1 — maturidade de engenharia

| Item | Por que importa | Status |
|---|---|---|
| RAG v2: busca híbrida, corpus ampliado e métrica de citação | O RAG atual é lexical sobre README + OpenAPI | Planejado |
| Observabilidade: métricas Prometheus e painel | Prova operação, não só código | Planejado |
| Hardening: CodeQL, Dependabot, `pip-audit`, Trivy e `SECURITY.md` | Sinaliza cuidado com supply chain | Planejado |
| Performance: cenário de carga com resultados versionados | Responde "aguenta tráfego?" com número | Planejado |
| Outbox pattern e replay de DLQ | Consistência entre banco e eventos | Planejado |
| Autenticação própria no microsserviço de inventário | Fecha a última superfície sem JWT | Planejado |

### P2 — diferenciais

| Item | Por que importa | Status |
|---|---|---|
| Assistente com *tool calling* (pedido/inventário) | Transforma chatbot em agente com dados reais | Planejado |
| Streaming de respostas (SSE) e histórico de conversa | Percepção de produto moderno | Planejado |
| Segundo provedor de LLM com roteamento por custo/latência | Demonstra abstração de provedor | Planejado |
| ADRs e diagramas C4 | Mostra decisão, não só implementação | Planejado |
| Front-end real (SPA ou HTMX) no lugar do mock | Elimina a maior limitação visual do MVP | Planejado |

## Relacionados

- Meta-spec da fase 2:
  [`00_diretriz_incremental_specdd_fase2.md`](00_diretriz_incremental_specdd_fase2.md)
- Template de incremento:
  [`_template_fase2_spec.md`](_template_fase2_spec.md)
- Evidências: [`docs/portfolio/evidencias/`](../docs/portfolio/evidencias/README.md)
- Histórico da fase 1: [`specs/`](../specs/README.md)
