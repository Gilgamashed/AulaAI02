# Changelog

Todas as alterações relevantes do projeto SynapseShop. O formato segue o
[*Keep a Changelog*](https://keepachangelog.com/pt-BR/1.1.0/) e o versionamento
é [SemVer](https://semver.org/lang/pt-BR/). O ficheiro foi criado na Aula 13 e
codifica retroativamente o histórico das aulas anteriores.

## [1.14.0] - 2026-10-09 — Aula 14

> Camada de IA do SynapseShop: assistente de logs com resiliência, privacidade
> e telemetria, exposto por um endpoint autenticado.

### Adicionado

- **`llm_service` (`api/core/llm/`, Aula 14):** fachada de IA com **timeout**
  (guarda genérica com executor), **retry** com backoff exponencial + *full
  jitter` e **circuit breaker** `closed/open/half-open`. Provedor atual é um
  **mock** determinístico em memória (sem rede, sem credenciais); o contrato
  `ProvedorLlm` é o ponto de encaixe do adaptador real no futuro. Provas de
  margem em `tests/unit/test_llm_resiliencia.py`.
- **`POST /api/v1/assist`:** sumariza/explica logs operacionais (`mode`
  `summarize`/`explain`). Exige JWT (qualquer papel); throttling `user` atua
  como cota de custo. `logs` aceita string ou array (máx. 100.000 chars, sem
  itens vazios), `temperature` (0.0–1.0, padrão 0.2) e `max_tokens` (1–4096,
  padrão 256). Resposta `{answer, meta:{tokens_prompt, tokens_output}}`;
  erros mapeados: `400/401/500/502/503`.
- **Privacidade e redação (`api/core/llm/redacao.py`, item 3 do DoD):** PII e
  segredos viram placeholders estáveis (`[EMAIL]`, `[CPF_CNPJ]`,
  `[TELEFONE]`, `[IP]`, `[CARTAO]`, `[TOKEN]`, `[SEGREDO]`, `[CREDENCIAL]`)
  antes do provedor e na resposta; bandeira `LLM_REDACAO_ATIVA`
  (default `true`). Testes em `tests/unit/test_llm_redacao.py`.
- **Telemetria (`api/core/llm/metricas.py`, item 3):** latência, taxa de erro,
  tokens e **custos estimados** por chamada; eventos JSON no logger
  `core.llm` (`LlmRespostaOk` inclui `latencia_ms` e `custo_usd`);
  `GET /api/v1/llm/metrics/` (admin) expõe o snapshot e a configuração.
  Preços de exemplo via `LLM_CUSTO_INPUT_POR_1M_TOKENS` /
  `LLM_CUSTO_OUTPUT_POR_1M_TOKENS`.
- **Testes do item 4 do DoD:** resiliência, redação, métricas, serializer
  (payload inválido) e integração do endpoint (401/200/400/500/502/503 + PII
  na resposta + `/llm/metrics` restrito ao admin). O `api/core/llm/*` voltou a
  entrar na métrica de cobertura (removido do `omit`); suíte em 222 testes,
  cobertura 89,91% (gate ≥ 85%).
- **Documentação da Aula 14** no `README.md` (arquitetura, templates de
  prompt, limites, política de redação, métricas) e contrato OpenAPI em
  `docs/openapi.yaml` (paths `/api/v1/assist` e `/api/v1/llm/metrics/`,
  schemas `AssistRequest`/`AssistResponse`/`LlmMetrics`, responses
  `BadGateway`/`InternalServerError`/`ServiceUnavailableLlm`) — linter Spectral
  em 0 erros/avisos.

### Corrigido

- **Sonda de circuito meio-aberto:** a chamada que abria o meio-aberto não
  contava como sonda, deixando passar `max_tentativas_half_open + 1`;
  agora a transição consome a 1ª sonda (docstring e teste garantem o limite).

### Pendências registadas

Registadas como issues no repositório — [#9 adaptador HTTP do provedor](https://github.com/Gilgamashed/AulaAI02/issues/9), [#10 agregação de métricas](https://github.com/Gilgamashed/AulaAI02/issues/10), [#11 guardrails](https://github.com/Gilgamashed/AulaAI02/issues/11), [#13 padrões de redação](https://github.com/Gilgamashed/AulaAI02/issues/13) e [#14 cache de respostas](https://github.com/Gilgamashed/AulaAI02/issues/14).

## [1.13.0] - 2026-10-08 — Aula 13

> Documentação completa da API: contrato OpenAPI/Swagger, linter estático,
> interfaces interativas e artefactos de consumo para integradores externos.

### Adicionado

- **Contrato OpenAPI** (`docs/openapi.yaml`, OpenAPI 3.1): 18 paths, 31
  operações e 40 schemas, com títulos, descrições, tags, exemplos de pedido e
  resposta.
- **Esquema de erros padronizado** (`ErrorSchema`, RFC 7807 /
  `application/problem+json`) com extensões `code` e `errors` (validação por
  campo), incluindo os respostas `400/401/403/404/409/429/503`.
- **Convenções estandardizadas no contrato-alvo**: paginação
  (`page`/`limit`/`nextCursor`), filtros (`?status=`, `?category=`,
  `?canal=`, faixa de preço), ordenação (`sort=<campo>:<dir>` /
  `?ordering=`) e cabeçalhos obrigatórios (`Authorization`,
  `Idempotency-Key`, `X-Trace-Id`), com notas de implementação apontando o
  comportamento atual do DRF (`PAGE_SIZE=20`, `?ordering=`, `{detail}`).
- **Validação estática reproduzível**: `scripts/lint-openapi.ps1` (Spectral,
  `extends: spectral:oas`) — **0 erros e 0 avisos**; instala o CLI em
  `.spectral-tools/` sem tocar no repositório.
- **Documentação interativa servida pela aplicação**: Swagger UI em
  `/docs/` e ReDoc em `/redoc/` (ambos alimentados por `/docs/openapi.yaml`),
  a partir de `api/core/wiki_docs.py`.
- **Coleção Postman** (`collections/synapseshop_aula13.postman_collection.json`):
  41 requisições com exemplos de sucesso e erro anexados, cobrindo o contrato
  ponta a ponta.
- **Environment Postman** (`collections/synapseshop_aula13.postman_environment.json`)
  com variáveis globais (`base_url`, `inventory_url`, `token`, `trace_id`,
  `idempotency_key`).
- **`docs/CHANGELOG.md`** (este ficheiro) e **Checklist do Integrador
  Externo** no `README.md`.

### Alterado

- `README.md`: nova secção *Checklist do Integrador Externo (Aula 13)*.
- `PROMPTS.md`: históricos da Aula 13 (DoDs 1–3 e 4–9).
- `.gitignore`: `.spectral-tools/` e `node_modules/`.

### Notas

- O contrato-alvo documenta `limit`/`nextCursor`/`sort`/`X-Trace-Id`; a
  implementação atual devolve paginação DRF (`page`/`PAGE_SIZE=20`) e
  `?ordering=`. As diferenças estão sinalizadas como notas no próprio
  `openapi.yaml` e no Checklist do Integrador.
- Nenhuma dependência nova no Docker (`requirements*`, `Dockerfile`,
  `docker-compose.yml` intocados).

## [1.12.0] - 2026-10-XX — Aula 12

- Testes automatizados e cobertura (perfil `tests` do Compose), convenções da
  equipe e metas de cobertura.

## [1.11.0] - 2026-10-05 — Aula 11

- Segundo fluxo Kafka: **pagamento e notificação**. Endpoint de pagamento com
  idempotência ponta a ponta (OneToOne, `pagamento.registrados`),
  `Notificacao` com filtros e permissões por dono, DLQ própria e contrato
  `docs/contracts/pagamento_registrado.md`.

## [1.10.0] - 2026-10-XX — Aula 10

- Apache Kafka: partições, offsets e DLQ; reentrega por retenção de tópico
  (5/15/45 s), `acks=all` + produtor idempotente, medição de latência e
  vazão/paralelismo.

## [1.9.0] - 2026-10-XX — Aula 9

- Mensageria assíncrona: Kafka (padrão) e RabbitMQ (profile), contrato do
  evento `PedidoCriado`, idempotência em duas barreiras e recuo com DLQ.

## [1.8.0] - 2026-10-XX — Aula 8

- Cache-aside com Redis para listagens e detalhes do catálogo, métricas de
  hit rate (`GET /api/v1/cache/metrics/`) e modo degradado.

## [1.7.0] - 2026-10-XX — Aula 7

- Autenticação JWT (SimpleJWT), papéis admin/user (`IsAdminRole`),
  throttling (`anon` 20/min, `user` 100/min, `login` 5/min) e matriz de
  permissões.

## [1.6.0] - 2026-10-XX — Aula 6

- Modelagem relacional (User no Django; InventoryItem no FastAPI), índices,
  migrações com Alembic e camadas Repository + Service.

## [1.5.0] - 2026-10-XX — Aula 5

- Microsserviço de estoque (FastAPI) no Compose (`:8001`), CRUD em
  `/api/v1/inventory`.

## [1.4.0] - 2026-10-XX — Aula 4

- CRUD DRF de categorias e itens sob `/api/v1/` com o mesmo PostgreSQL.

## [1.0.0] – [1.3.0] — Aulas 1 a 3

- MVP do backend de pedidos, arquitetura em 6 camadas, Dockerfile multistage
  e orquestração com Docker Compose (7 serviços).