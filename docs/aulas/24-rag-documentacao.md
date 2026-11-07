# Assistente de Documentação com RAG (Aula 24)

## Objetivo

Responder perguntas técnicas sobre o próprio projeto usando **RAG**
(Retrieval-Augmented Generation): a documentação é dividida em chunks,
vetorizada e indexada; a pergunta recupera os trechos mais próximos e a
resposta é obrigatoriamente acompanhada da fonte exata — caminho, título,
intervalo de caracteres e pontuação.

```
pergunta → embedding → cosseno (top_k + min_score) → prompt com contexto
        → provedor de IA → answer + sources
```

Sem recuperação acima do limiar, a LLM **não é chamada**: a resposta é o
guardrail de "informação não encontrada" com `sources: []`.

## Arquitetura

```
api/core/ask_docs/
├── constantes.py   # defaults, fontes, frase de guardrail
├── erros.py        # erros previsíveis (índice, fonte, parâmetro)
├── chunking.py     # divisão ~400 tokens / ~80 overlap + passagens
├── embeddings.py   # TF-IDF local, vocabulário exato, cosseno, BLOB
├── indice.py       # SQLite: documents, chunks, vocabulario; busca top-k
├── ingestao.py     # hash, leitura das fontes, chunking, gravação atômica
├── prompt.py       # contexto numerado + regras do system prompt
├── servico.py      # orquestra recuperação, guardrail e LLM
├── serializers.py  # contrato de entrada {question, top_k, min_score}
└── views.py        # POST /api/v1/ask_docs/ e mapa de erros HTTP

api/core/llm/
├── mock_docs.py    # provedor extrativo determinístico (porta ProvedorLlm)
└── servico.py      # fábrica por tarefa: assist | sql | docs

api/core/management/commands/indexar_docs.py  # CLI de ingestão
```

A view é fina: valida o payload, delega ao serviço e traduz os desfechos em
HTTP. Toda a lógica de RAG fica no pacote `ask_docs`, testável sem HTTP.

## Modelagem do índice

SQLite separado do banco de negócio (`ASK_DOCS_INDEX_PATH`, padrão
`data/rag_index.sqlite3`; no Compose `/app/data/rag_index.sqlite3`).

| Tabela | Colunas |
| --- | --- |
| `documents` | `doc_id`, `path` (único), `title`, `hash`, `indexed_at` |
| `chunks` | `chunk_id`, `doc_id` (FK), `chunk_text`, `start`, `end`, `embedding` BLOB, `dim` |
| `vocabulario` | `term`, `idf`, `indice` |

`start`/`end` são o intervalo de caracteres no documento original — é o valor
devolvido em `sources[].range`. `hash` é o SHA-256 do conteúdo: se nenhum hash
mudou e já existem chunks, a ingestão não reindexa.

## Ingestão

1. Lê `README.md` e `docs/openapi.yaml` (`ASK_DOCS_SOURCES`), recusando
   caminhos fora da raiz do projeto.
2. Calcula o hash de cada fonte.
3. Divide cada documento em blocos de ~400 tokens com ~80 de overlap
   (`ASK_DOCS_CHUNK_TOKENS`, `ASK_DOCS_CHUNK_OVERLAP`).
4. Calcula o IDF do corpus e gera o embedding TF-IDF normalizado de cada
   chunk.
5. Substitui documentos, vocabulário e chunks numa única transação.

Quando qualquer fonte muda, o índice inteiro é reconstruído. O corpus é
pequeno e a reconstrução integral mantém o IDF consistente com todos os
vetores gravados.

### Comando

```bash
# Idempotente por hash (usado no startup da API)
python api/manage.py indexar_docs

# Força a reconstrução
python api/manage.py indexar_docs --force

# Outro índice, raiz ou conjunto de fontes
python api/manage.py indexar_docs \
  --index-path data/rag_index.sqlite3 \
  --root . \
  --source README.md --source docs/openapi.yaml
```

No Compose, o startup executa `migrate` e depois `indexar_docs`; o volume
nomeado `rag_data` preserva o arquivo entre recriações do container.

## Embeddings locais

A Aula 14 decidiu não depender de rede nem de credenciais para a camada de
IA. O RAG mantém a decisão: em vez de um modelo neural, o vetor é TF-IDF com
**vocabulário exato** e norma L2.

- Tokens são normalizados (minúsculas, sem acentos) e stopwords de português
  e inglês são descartadas.
- A dimensão do vetor é o tamanho do vocabulário do corpus, persistido em
  `vocabulario`; não há colisão de hash.
- Termos desconhecidos não entram no vetor. Uma pergunta inteiramente fora do
  vocabulário gera vetor zero e cai no guardrail.
- A serialização usa `float32` num BLOB; a coluna `dim` valida a leitura.

A pontuação de um chunk é o **maior cosseno** entre o chunk inteiro e as
passagens (frases/parágrafos) dentro dele. O chunk continua sendo a unidade de
citação; a passagem só refina o ranking.

## Recuperação e guardrail

- `top_k`: padrão 3, teto `ASK_DOCS_MAX_TOP_K` (10).
- `min_score`: padrão 0.25, faixa 0–1.
- O ranking ordena por `score` decrescente e desempata por `chunk_id`.
- Se a lista final estiver vazia, o serviço devolve a frase de guardrail e
  `sources: []` **sem chamar a LLM**.

## Contrato HTTP

`POST /api/v1/ask_docs/` — JWT obrigatório, papel `admin`.

Entrada:

```json
{
  "question": "As migrações do banco rodam automaticamente no startup?",
  "top_k": 3,
  "min_score": 0.25
}
```

Saída (200):

```json
{
  "answer": "As migrações são aplicadas automaticamente no startup (o banco já está saudável via `depends_on`). [1]",
  "sources": [
    {
      "path": "README.md",
      "title": "SynapseShop",
      "range": "24658-27472",
      "score": 0.3213
    }
  ]
}
```

Guardrail (200):

```json
{
  "answer": "Não encontrei essa informação na documentação do projeto. Tente reformular a pergunta ou consulte o README.md e o contrato OpenAPI.",
  "sources": []
}
```

Mapa de erros:

| Status | Situação |
| --- | --- |
| 400 | payload inválido (`question` vazia/ > 500, `top_k` fora de 1–10, `min_score` fora de 0–1) |
| 401 | sem JWT |
| 403 | sem papel admin |
| 500 | camada de IA mal configurada |
| 502 | provedor devolveu resposta inválida |
| 503 | índice ausente/indisponível ou provedor fora do ar |

## Provedor mock

`ProvedorMockDocs` cumpre a mesma porta `ProvedorLlm` e é selecionado por
`criar_llm_service(tarefa="docs")`. Ele:

1. extrai a pergunta e os blocos do prompt;
2. escolhe o bloco com maior sobreposição de tokens com a pergunta;
3. extrai a passagem mais sobreposta e acrescenta a citação `[n]`.

O que é mock e o que é real:

| Parte | Natureza |
| --- | --- |
| Síntese em linguagem natural | mock extrativo determinístico |
| Chunking, embeddings, índice, cosseno, top-k, min_score, guardrail, contrato, testes | real |

## Testes

| Arquivo | Cobertura |
| --- | --- |
| `tests/unit/test_ask_docs_chunking.py` | cadência 400/80, offsets, overlap, passagens |
| `tests/unit/test_ask_docs_embeddings.py` | IDF, vocabulário, normalização, cosseno, BLOB |
| `tests/unit/test_ask_docs_indice.py` | schema, substituição atômica, ranking, `min_score` |
| `tests/unit/test_ask_docs_ingestao.py` | hash, fontes, reindexação, chunking configurável |
| `tests/unit/test_ask_docs_servico.py` | guardrail sem LLM, fontes, `top_k`, parâmetros |
| `tests/unit/test_ask_docs_prompt.py` | contexto numerado, mock extrativo, citação |
| `tests/integration/test_ask_docs_endpoint.py` | 401/403/400, caminho feliz, guardrail, 502/503 |

## Limitações registradas

- O mock **não sintetiza** como um LLM neural: ele extrai e cita. Um adaptador
  real entra pela mesma porta sem mudar índice, recuperação ou contrato.
- A semântica é lexical: sinônimos sem radicais/tokens em comum podem não se
  aproximar. Modelos neurais de embedding são a evolução natural quando houver
  rede/credenciais.
- Apenas as fontes configuradas são indexadas. Não há UI de upload, banco
  vetorial externo nem reindexação automática por alteração de arquivo — o
  startup e o comando manual cobrem o escopo da aula.
