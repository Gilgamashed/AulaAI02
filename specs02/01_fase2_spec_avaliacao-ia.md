# 01 — Avaliação Mensurável dos Pilares de IA

## 1. Objetivo de portfólio

Transformar "a IA funciona nas perguntas da demo" em um número defensável:
medir, por categoria, a taxa de sucesso de `/ask_sql`, `/ask_docs` e `/assist`
antes de qualquer correção, com relatório reproduzível e taxonomia de erros.
Este incremento produz o baseline que a spec `02` usa para provar melhoria.

## 2. Contexto e problema

O documento [`docs/portfolio/preparacao`](../docs/portfolio/preparacao) registra
que perguntas de demonstração funcionam, mas perguntas livres do usuário
frequentemente falham. A investigação encontrou causas concretas no validador
de SQL (`api/core/ask_sql/validacao.py`):

| SQL plausível gerado pelo modelo | Resultado atual | Causa |
|---|---|---|
| `EXTRACT(YEAR FROM created_at)` | `SqlProibido` | `_REFERENCIA_TABELA` interpreta `FROM created_at` como tabela |
| `jsonb_array_elements(p.itens)` | `SqlProibido` | junção por vírgula bloqueada; é o caminho para itens do pedido |
| `SELECT *` | `SqlProibido` | regra de projeção; o modelo desobedece ao prompt |
| `"core_pedido"` | `SqlInvalido` | identificadores entre aspas bloqueados |
| `p.id AS owner` | `SqlProibido` | `PALAVRAS_PROIBIDAS` casa com alias |

Além disso, não existe loop de reparo: a validação reprova e o usuário recebe
422, sem que o modelo seja informado do erro. Sem um golden set, também não há
como distinguir "o modelo errou" de "o validador rejeitou uma consulta válida".

O RAG (`api/core/ask_docs/embeddings.py`) é lexical (TF-IDF) sobre
`README.md` + `docs/openapi.yaml`, com `ASK_DOCS_MIN_SCORE=0.25`; perguntas com
sinônimos caem no guardrail. O `/assist` resume logs, sem consultar dados.

**Este incremento não corrige nada disso.** Ele mede.

## 3. Escopo

### 3.1. Golden set versionado

Criar `scripts/avaliacao_ia/golden_set.json` com, no mínimo, **46 itens**
distribuídos nestas categorias (mais 3 itens complementares de `assist`):

| Categoria | Mínimo | Exemplo de pergunta |
|---|---|---|
| `contagem` | 4 | "Quantos pedidos existem?" |
| `listagem` | 4 | "Liste os 10 produtos mais recentes" |
| `agregacao` | 6 | "Qual o ticket médio dos pedidos?" |
| `serie_temporal` | 5 | "Qual o faturamento por mês?" |
| `join` | 5 | "Quais clientes fizeram mais pedidos?" |
| `jsonb_itens` | 5 | "Quais produtos foram mais vendidos em quantidade?" |
| `ranking` | 4 | "Quais os 5 produtos mais caros?" |
| `fora_dominio` | 4 | "Qual o endereço de entrega do pedido 1?" |
| `rag_tecnico` | 6 | "Como funciona o cache do catálogo?" |
| `rag_fora_corpus` | 3 | "Qual a política de troca da loja?" |
| `assist` (complementar) | 3 | "Resuma este log de erro" |

A categoria `assist` é complementar: mede o terceiro pilar citado no objetivo,
mas **não entra no gate** de `--min-sucesso`, que considera apenas `consulta`
(texto-para-SQL) e `rag_tecnico`.

Formato:

```json
{
  "versao": 1,
  "atualizado_em": "2026-11-16",
  "itens": [
    {
      "id": "sql-serie-01",
      "categoria": "serie_temporal",
      "endpoint": "/api/v1/ask_sql/",
      "pergunta": "Qual o faturamento por mês nos últimos 6 meses?",
      "tipo_resultado": "consulta",
      "esperado": {
        "status": 200,
        "colunas_min": ["mes", "receita"],
        "fontes_min": 0
      },
      "tags": ["ci_mock", "gemini"]
    }
  ]
}
```

Regras:

- `tipo_resultado` é `consulta`, `recusa_esperada`, `guardrail_esperado`,
  `rag_tecnico` ou `assist`. Os dois últimos classificam os pilares que não
  são SQL e não entram no gate de 90%.
- `esperado.colunas_min` aceita uma string (coluna obrigatória) ou uma lista
  de alternativas aceitáveis, porque o Gemini escolhe aliases. Itens
  `ci_mock` usam o alias determinístico do mock.
- `esperado.linhas_min` é opcional (padrão `0`) e detecta consulta `200`
  semanticamente vazia.
- Pelo menos **10** perguntas de `consulta` devem estar fora dos padrões do
  mock (`api/core/llm/mock_sql.py`), para que o baseline reflita uso real.
- Pelo menos **20** itens levam a tag `ci_mock`; o restante pode ser medido
  apenas com Gemini.
- Nenhuma pergunta contém PII, credencial ou dado que dependa de estado
  mutável. As expectativas são estruturais (status, colunas, fontes), nunca o
  SQL exato.
- O arquivo é validado pelo próprio harness: item sem campo obrigatório ou
  categoria desconhecida falha antes de qualquer chamada HTTP.

### 3.2. Harness `scripts/avaliar_ia.py`

Script Python 3.12+ com apenas biblioteca padrão (`urllib`, `json`,
`argparse`), no mesmo estilo de `scripts/validar_mvp.py`.

Interface:

```bash
python scripts/avaliar_ia.py \
  --base-url http://localhost:8000 \
  --golden-set scripts/avaliacao_ia/golden_set.json \
  --saida docs/portfolio/evidencias/ia \
  --max-questions 0 \
  --min-sucesso 0.8

python scripts/avaliar_ia.py --dry-run   # valida o golden set, sem rede
python scripts/avaliar_ia.py --categorias join,jsonb_itens,serie_temporal
```

Requisitos:

- Autenticar em `POST /api/v1/auth/token/` com `demo_admin`; usuário e senha
  vêm de argumentos ou das variáveis `AVALIACAO_IA_USUARIO` /
  `AVALIACAO_IA_SENHA`. Nunca imprimir senha nem token.
- Executar cada item no endpoint indicado, com `timeout` configurável e
  `--delay` entre chamadas (padrão `0.5s`) para respeitar rate limit.
- Classificar o desfecho:
  - `consulta`: 200 + colunas mínimas presentes (comparação sem diferenciar
    maiúsculas) + `row_count` coerente;
  - `recusa_esperada`: 422 com `detail`;
  - `guardrail_esperado`: 200 com `sources` vazio e a frase padrão do RAG.
- Taxonomia de falha, derivada de status + `detail`:
  `auth`, `http_4xx_inesperado`, `http_5xx`, `indice_ausente`,
  `nao_suportado`, `sql_proibido`, `sql_invalido`, `execucao_falhou`,
  `sem_fonte`, `sem_citacao`, `resposta_vazia`, `timeout`, `resposta_inesperada`.
- Medir latência por item e tokens quando a resposta trouxer `meta`.
- Gerar dois artefatos em `--saida`:
  - `AAAA-MM-DD_HHMM_<modo>.json` com metadados (commit git, horário,
    `base_url`, provedor configurado/efetivo, modelo, versão do golden set) e
    resultado de cada item;
  - `AAAA-MM-DD_HHMM_<modo>.md` com taxa de sucesso geral e por categoria,
    ranking das falhas, p50/p95 de latência, tokens totais e limitações.
- Código de saída `0` somente se: golden set válido, autenticação ok e taxa de
  sucesso ≥ `--min-sucesso` **considerando apenas** `consulta` e `rag_tecnico`;
  recusas e guardrails esperados contam como comportamento correto.
- `--dry-run` não faz chamadas e retorna `0` apenas com golden set válido.
- Falha de rede deve ser reportada com item, status e corpo resumido, sem
  interromper os demais itens.

### 3.3. Baseline medido

Executar o harness com a stack completa:

1. `docker compose up -d --build db api dashboard`
2. `python api/manage.py seed_auth`
3. `python api/manage.py seed_demo --com-inventario`
4. `python api/manage.py indexar_docs`
5. duas execuções, salvando relatórios distintos:
   - `LLM_PROVIDER=mock`;
   - `LLM_PROVIDER=auto` (Gemini quando a chave estiver disponível).

O relatório deve declarar explicitamente qual provedor foi usado. Se o Gemini
não estiver disponível, o baseline de mock é o mínimo aceitável para encerrar o
incremento, com a lacuna registrada no relatório.

### 3.4. Regressão em CI

- `tests/unit/test_avaliacao_ia.py`: validação do golden set (campos, contagens
  mínimas, categorias), taxonomia, agregação do relatório, `--dry-run` e
  códigos de saída, com servidor HTTP falso no padrão de
  `tests/unit/test_validar_mvp.py`.
- `tests/integration/test_golden_set_ask_sql.py`: com `LLM_PROVIDER=mock`,
  executar os itens `ci_mock` no cliente de teste do Django e garantir que o
  comportamento esperado (`200` para `consulta`, `422` para `recusa`) se
  mantém. Este teste é a linha de base de regressão da spec `02`.

## 4. Fora de escopo

- Corrigir o validador, o prompt, o mock ou o RAG — isso é a spec `02` e os
  incrementos seguintes.
- Novos endpoints, modelos, migrations ou variáveis de ambiente.
- Deploy, performance, segurança de supply chain, observabilidade.
- Dashboard para consumir os relatórios.
- Uso de bibliotecas externas no harness.

## 5. Métricas de sucesso e evidências

| Métrica | Antes | Meta | Como medir |
|---|---|---|---|
| Cobertura do golden set | — | ≥ 46 itens, 10 categorias | `--dry-run` |
| Taxa de sucesso (`consulta`) | desconhecida | medida e publicada | relatório JSON/MD |
| Taxa de sucesso (`rag_tecnico`) | desconhecida | medida e publicada | relatório JSON/MD |
| Erros por categoria | desconhecida | ranking completo | relatório MD |
| Latência p50/p95 | desconhecida | medida | relatório JSON/MD |
| Reproducibilidade | — | duas execuções, mesma classificação | comparação manual |

Evidências em `docs/portfolio/evidencias/ia/`:

- `AAAA-MM-DD_HHMM_mock.json` e `.md`;
- `AAAA-MM-DD_HHMM_gemini.json` e `.md` (quando disponível);
- link para os dois no `specs02/README.md`.

## 6. Testes exigidos

- Golden set válido, sem IDs duplicados, com as contagens mínimas por categoria.
- Harness: login, sucesso, recusa esperada, guardrail, erro HTTP, timeout e
  `--dry-run`.
- Relatório: agregação por categoria, p50/p95, taxa e `min-sucesso`.
- Regressão `ci_mock` no Django com mock determinístico.
- Suíte existente permanece verde, ≥ 578 testes e cobertura ≥ 85%.
- `ruff check .` e `mypy api services dashboard` verdes.

## 7. Definition of Done

- [ ] `scripts/avaliacao_ia/golden_set.json` com ≥ 46 itens e 10 categorias
      obrigatórias, mais 3 itens complementares de `assist`.
- [ ] `scripts/avaliar_ia.py` executa ponta a ponta e falha com código != 0
      quando a taxa fica abaixo de `--min-sucesso`.
- [ ] Relatórios de baseline (mock e, se possível, Gemini) publicados em
      `docs/portfolio/evidencias/ia/`.
- [ ] Taxa de sucesso e distribuição de erros publicadas no `specs02/README.md`.
- [ ] Testes novos verdes e suíte global ≥ 578 testes, cobertura ≥ 85%.
- [ ] `ruff check .` e `mypy api services dashboard` verdes.
- [ ] `docs/CHANGELOG.md` e `PROMPTS.md` atualizados.
- [ ] Nenhuma alteração no pipeline de IA além do necessário para medir.

## 8. Riscos e rollback

- **Custo/rate limit do Gemini:** `--delay`, `--max-questions` e execução
  primeiro em mock; o relatório registra consumo.
- **Não determinismo do modelo:** expectativas estruturais, `temperature=0` já
  usado pelo pipeline, e registro de modelo/versão no relatório.
- **Massa de dados variável entre execuções:** `seed_demo` é idempotente;
  perguntas não dependem de contagem exata, apenas de forma e faixa.
- **Índice RAG ausente:** o harness classifica como `indice_ausente` e o
  relatório instrui `python api/manage.py indexar_docs`.
- **Credencial demo alterada:** falha explícita de `auth`, sem expor a senha.
- **Rollback:** o incremento só adiciona script, dados e testes; remover os
  arquivos e o commit não afeta o produto.

## 9. Dependências

- Stack de pé (`docker compose up -d --build`).
- `seed_auth` e `seed_demo --com-inventario` executados.
- `indexar_docs` executado.
- Baseline da fase 1 na tag `apresentacao-final`.
- Nenhuma dependência dos incrementos seguintes.
