# Aula 25 — IA real com Google Gemini

Este documento descreve o adaptador Gemini que substitui, por configuração, os
provedores mock dos três recursos de IA do SynapseShop:

- `POST /api/v1/assist/` — assistente de suporte;
- `POST /api/v1/ask_sql/` — texto-para-SQL;
- `POST /api/v1/ask_docs/` — assistente de documentação (RAG).

O mock continua sendo o padrão de testes/CI e o plano B da apresentação.

## Arquitetura

```
View DRF
  └─ criar_llm_service(tarefa=...)
       ├─ LlmService (timeout, retry+backoff+jitter, circuit breaker, métricas)
       │    └─ ProvedorLlm (porta)
       │         ├─ ProvedorMock / ProvedorMockSql / ProvedorMockDocs
       │         └─ ProvedorGemini (google-genai)
       └─ seleção por LLM_PROVIDER=mock|gemini
```

Decisões:

- **A resiliência não muda.** `ProvedorGemini` só traduz a porta
  `ProvedorLlm` para o SDK; retry, timeout, breaker e métricas continuam em
  `LlmService`.
- **Singleton e breaker por tarefa.** `assist`, `sql` e `docs` têm circuit
  breakers independentes, para que uma falha em SQL não derrube o assistente.
- **Import tardio do SDK.** Quem roda apenas com `LLM_PROVIDER=mock` não
  carrega o cliente HTTP do Google.
- **Cliente injetável.** A suíte usa dublês e nunca toca a rede.
- **Sem fallback automático.** Uma chave inválida falha de forma explícita
  (HTTP 500); o plano B é trocar `LLM_PROVIDER=mock` e reiniciar a API.
- **Contexto do RAG é dado, não instrução.** As regras ficam no `system` e o
  contexto recuperado vai na mensagem `user`; o modelo é instruído a ignorar
  comandos contidos nos documentos (defesa contra prompt injection).
- **Bloqueio é resposta inválida.** O adaptador lê `finish_reason` e
  `prompt_feedback.block_reason`; conteúdo bloqueado vira `RespostaInvalida`
  (HTTP 502), mesmo que o provedor devolva texto parcial.

## Configuração

No `.env` (gitignored):

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=sua-chave-do-google-ai-studio
LLM_MODEL=gemini-3.5-flash
LLM_MODEL_SQL=gemini-3.5-flash
LLM_MODEL_DOCS=gemini-3.5-flash
LLM_TIMEOUT_SEGUNDOS=30.0
LLM_MAX_TENTATIVAS=3
LLM_BACKOFF_BASE_SEGUNDOS=0.5
LLM_REDACAO_ATIVA=true
```

Observações:

- `LLM_MODEL*` pode continuar com os valores históricos `mock`,
  `mock-sql` e `mock-docs`: ao selecionar Gemini, a fábrica troca esses
  defaults por `gemini-3.5-flash`.
- `LLM_TIMEOUT_SEGUNDOS` de 20–30 s é mais realista para o provedor externo;
  o prompt de SQL é o maior dos três e foi o que exigiu 30 s na validação. O
  mock responde em milissegundos.
- O `docker-compose.yml` repassa `GEMINI_API_KEY` para a API e força
  `LLM_PROVIDER=mock` no serviço `tests`, para que a suíte nunca chame a API
  real mesmo que o `.env` esteja configurado para a apresentação.
- A chave nunca é copiada para a imagem, impressa em log ou devolvida por
  endpoint. O `/api/v1/llm/metrics/` mostra provedor, modelo efetivo da tarefa
  `assist` e o mapa `modelos` com `assist`, `sql` e `docs`; nunca a chave.

## Como obter a chave

1. Acesse o Google AI Studio.
2. Crie uma API key em um projeto com a API Generative Language habilitada.
3. Cole o valor **apenas** no `.env` local ou em um secret do ambiente.
4. Reinicie a API: `docker compose up -d api`.

Não versione o `.env` e não cole a chave em issues, prints ou no `PROMPTS.md`.

## Modelos e custos

O modelo sugerido é `gemini-3.5-flash`, escolhido por equilíbrio entre
latência e custo para as três tarefas. Modelos maiores podem ser usados
trocando `LLM_MODEL*`.

Os nomes de modelos mudam com o tempo: o `gemini-2.5-flash`, sugerido na
primeira versão desta aula, foi aposentado para chaves novas durante a
validação (HTTP 404). O default do adaptador passou a ser
`gemini-3.5-flash`. Confirme os modelos disponíveis para a sua chave com
`client.models.list()` e ajuste `LLM_MODEL*` se necessário.

O adaptador envia `thinking_config.thinking_budget=0` aos modelos Flash. Sem
isso, o orçamento de saída pode ser consumido por tokens de raciocínio e a
resposta volta vazia (ou a chamada estoura o timeout) — o que foi observado
na validação com orçamentos curtos. Desligar o "thinking" também mantém a
latência previsível para uma API síncrona.

Os custos por 1M de tokens são configuráveis e usados apenas para a estimativa
em `/api/v1/llm/metrics/`:

```env
LLM_CUSTO_INPUT_POR_1M_TOKENS=0.30
LLM_CUSTO_OUTPUT_POR_1M_TOKENS=2.50
```

Confirme os valores vigentes na página oficial de preços do Google antes de
usar a estimativa em uma apresentação. O projeto não faz cobrança nem controla
cota: o limite real é o da conta Google.

## Como testar

### PowerShell

```powershell
$login = Invoke-RestMethod -Method Post `
  -Uri 'http://localhost:8000/api/v1/auth/token/' `
  -ContentType 'application/json' `
  -Body '{"username":"demo_admin","password":"<senha>"}'

$headers = @{ Authorization = "Bearer $($login.access)" }

Invoke-RestMethod -Method Post `
  -Uri 'http://localhost:8000/api/v1/assist/' `
  -Headers $headers -ContentType 'application/json' `
  -Body '{"mode":"summarize","logs":"ERROR timeout ao conectar no banco","max_tokens":128}'

Invoke-RestMethod -Method Post `
  -Uri 'http://localhost:8000/api/v1/ask_sql/' `
  -Headers $headers -ContentType 'application/json' `
  -Body '{"question":"Quantos pedidos existem por status?"}'

Invoke-RestMethod -Method Post `
  -Uri 'http://localhost:8000/api/v1/ask_docs/' `
  -Headers $headers -ContentType 'application/json' `
  -Body '{"question":"Como rodar os testes?","top_k":3,"min_score":0.25}'
```

### bash/curl

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo_admin","password":"<senha>"}' |
  python -c 'import json,sys; print(json.load(sys.stdin)["access"])')

curl -s -X POST http://localhost:8000/api/v1/ask_docs/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Como rodar os testes?","top_k":3,"min_score":0.25}'
```

O `ask_docs` exige o índice construído:

```bash
docker compose exec api python api/manage.py indexar_docs
```

O smoke automático cobre os três endpoints:

```bash
python scripts/validar_mvp.py
python scripts/validar_mvp.py --skip-ai
```

## Voltar para o mock

```env
LLM_PROVIDER=mock
LLM_MODEL=mock
LLM_MODEL_SQL=mock-sql
LLM_MODEL_DOCS=mock-docs
LLM_TIMEOUT_SEGUNDOS=5.0
```

```bash
docker compose up -d api
```

O mock preserva todo o comportamento dos endpoints, sem rede e sem custo. É o
padrão da suíte e do CI.

## Mapeamento de erros

| Condição do Gemini | Exceção da camada | HTTP |
| ------------------ | ----------------- | ---- |
| chave ausente/vazia | `LlmConfiguracaoInvalida` | 500 |
| 401/403 (credencial) | `LlmConfiguracaoInvalida` | 500 |
| 400/404 (requisição/modelo) | `LlmErroCliente` | 502 |
| 429 (rate limit) | `LlmRateLimit` com `retry_after` | 503 após esgotar retries |
| 500/502/503/504 | `LlmErroServidor` | 503 após esgotar retries |
| timeout de transporte | `LlmTimeout` | 503 |
| falha de conexão/DNS | `LlmConexao` | 503 |
| resposta vazia/bloqueada | `RespostaInvalida` | 502 |

A política de retry existente decide o que é recuperável; o adaptador não
reimplementa retry. Erros 4xx terminais não são retentados. O `finish_reason`
(`SAFETY`, `RECITATION`, `BLOCKLIST`, `PROHIBITED_CONTENT`, `SPII` e
correlatos) e o `prompt_feedback.block_reason` são verificados antes do texto:
um bloqueio nunca é devolvido como resposta válida.

## Troubleshooting

- **HTTP 500 “camada de IA mal configurada”:** `GEMINI_API_KEY` ausente,
  vazia ou rejeitada. Confira o `.env`, reinicie a API e veja o log
  `core.llm` (a chave não aparece nele).
- **HTTP 429:** cota/rate limit da conta Google. Aguarde o `retry_after` ou
  reduza a frequência; o breaker pode abrir temporariamente.
- **HTTP 502 “resposta inválida”:** conteúdo bloqueado por segurança ou
  resposta sem texto. Reformule o prompt; para logs, remova dados sensíveis.
- **HTTP 503:** provedor indisponível, timeout ou circuito aberto. Verifique
  conectividade do container (`docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('https://generativelanguage.googleapis.com', timeout=10).status)"`).
- **Latência alta:** use `gemini-3.5-flash` e `LLM_TIMEOUT_SEGUNDOS=30.0`;
  o prompt de SQL é o mais longo e pode estourar 20 s no primeiro uso.
  Acompanhe `/api/v1/llm/metrics/`.
- **`ask_docs` com `sources: []`:** guardrail acionado — a pergunta não tem
  chunk acima de `min_score`. Reformule ou reindexe com `indexar_docs`.
- **Modelo indisponível (404):** confirme o nome em `LLM_MODEL*`; o default
  seguro é `gemini-3.5-flash`.

## Limitações

- **RAG lexical:** os embeddings do índice continuam sendo TF-IDF locais;
  esta aula não introduz embeddings neurais nem banco vetorial externo.
  Sinônimos sem tokens em comum podem não ser recuperados.
- **Custo e rede:** o Gemini real depende de conectividade e consome cota. O
  mock existe justamente para testes determinísticos e para o plano B.
- **Sem streaming, tools ou agentes:** o escopo é completar texto pela mesma
  porta `ProvedorLlm`.
- **Sem fallback automático:** a troca de provedor é uma decisão explícita no
  `.env`, para não mascarar erro de configuração.
- **Redação de PII:** continua aplicada antes do envio e na resposta, mas não
  substitui a revisão humana do conteúdo colado na demo.

## Arquivos relacionados

- `api/core/llm/gemini.py` — adaptador;
- `api/core/llm/servico.py` — fábrica e seleção por tarefa;
- `api/core/llm/erros.py` — taxonomia neutra;
- `tests/unit/test_llm_gemini.py` — testes do adaptador e da fábrica;
- `specs/spec_da_aula_25_gemini.md` — spec normativa.
