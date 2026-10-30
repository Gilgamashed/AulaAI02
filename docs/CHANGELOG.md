# Changelog

Todas as alterações relevantes do projeto SynapseShop. O formato segue o
[*Keep a Changelog*](https://keepachangelog.com/pt-BR/1.1.0/) e o versionamento
é [SemVer](https://semver.org/lang/pt-BR/). O ficheiro foi criado na Aula 13 e
codifica retroativamente o histórico das aulas anteriores.

## [1.22.0] - 2026-10-30 — Pipeline de CI/CD com GitHub Actions

### Adicionado
- **Workflow `.github/workflows/ci.yml` (Aula 22):** dispara em `push` para `main`, `master` e `dev`, em `pull_request` para o branch principal e por `workflow_dispatch`.
- **Job `test-and-lint`:** Python 3.12, PostgreSQL 16 efêmero para o banco `test_*`, `ruff check .`, suíte `pytest` completa (gate de cobertura de 85% herdado do `pyproject.toml`) e publicação de `reports/junit.xml`, `reports/coverage.xml` e `htmlcov/` como artefatos.
- **Job `docker-build`:** `docker build -t synapseshop-api:test .` para validar o Dockerfile multistage e o empacotamento da imagem da API.
- **Ambiente de CI:** `DATABASE_URL` para o serviço PostgreSQL; `DJANGO_SECRET_KEY` lido de `secrets` com fallback efêmero; `DJANGO_DEBUG`, `MENSAGERIA_BROKER` e `ASK_SQL_*` fixados.
- **Ruff pinado:** `ruff==0.16.8` no `requirements-dev.txt`, garantindo o mesmo linter no host, no container de testes e no CI.
- **Relatórios locais:** `reports/` no `.gitignore`.

### Documentação
- **README:** badge de status do workflow e seção “Pipeline de CI/CD com GitHub Actions (Aula 22)” com triggers, jobs, variáveis/segredos, equivalente local e limites.
- **`docs/aulas/22-ci-cd.md`:** arquitetura do pipeline, PostgreSQL efêmero, isolamento de Redis/brokers e roteiro de reprodução.
- **`specs/README.md`:** índice da Aula 22.
- **`PROMPTS.md`:** registro do uso de IA na especificação e implementação do workflow.

### Notas
- Deploy contínuo, publicação em registry (DockerHub/GHCR) e cache avançado de dependências ficam para a Aula 23.

## [1.21.0] - 2026-10-28 — Consulta de Dados em Linguagem Natural (Texto-para-SQL)

### Adicionado
- **Endpoint `POST /api/v1/ask_sql/` (Aula 21):** pergunta em português → SQL somente leitura → linhas em JSON (`question`, `sql`, `columns`, `rows`, `row_count`, `truncated`, `meta`). Restrito ao papel `admin` (`IsAdminRole`) e ao JWT.
- **Pipeline `api/core/ask_sql/`:** allow-list de tabelas/colunas (`constantes.py`), contexto de schema (`schema.py`), system prompt (`prompt.py`), extração tolerante a markdown (`extracao.py`), validação (`validacao.py`), execução read-only (`execucao.py`), orquestração (`servico.py`), serializer e view com mapa de erros 400/401/403/422/500/502/503.
- **Provedor `ProvedorMockSql` (Aula 21):** mock determinístico na mesma porta `ProvedorLlm` da Aula 14, sem rede/credenciais; traduz os padrões de negócio do DoD e devolve `NAO_SUPORTADO` para o restante.
- **Fábrica por tarefa:** `criar_llm_service(tarefa="assist"|"sql")`, com singleton e circuit breaker independentes; setting `LLM_MODEL_SQL`.
- **Painel Streamlit:** página `dashboard/pages/3_Consulta_em_Linguagem_Natural.py` (login, pergunta, SQL em `st.code`, resultado em `st.dataframe`) e cliente HTTP `dashboard/ask_sql.py` (somente biblioteca padrão).
- **Configuração:** `ASK_SQL_MAX_LINHAS` (200), `ASK_SQL_TIMEOUT_MS` (3000), `ASK_SQL_MAX_TOKENS` (500), `ASK_SQL_LOG_LEVEL`, `DASHBOARD_API_URL` no Compose/`.env.example`; logger `core.ask_sql`.
- **Testes:** `tests/unit/test_ask_sql_{schema,validacao,extracao,mock}.py`, `tests/unit/test_dashboard_ask_sql.py` e `tests/integration/test_ask_sql_endpoint.py` (inclui prova de que a transação read-only recusa escrita).
- **Documentação:** `docs/aulas/21-consulta-linguagem-natural.md`, README, `PROMPTS.md`, `specs/README.md` e OpenAPI.

### Segurança
- Validação independente do modelo: apenas `SELECT`/`WITH`, um comando, sem comentários/aspas/`$`, allow-list de tabelas e colunas, sem `SELECT *`, sem `FOR UPDATE`, sem `pg_catalog`/`information_schema` e sem funções perigosas.
- Execução em transação `READ ONLY` com `statement_timeout` local e `LIMIT` obrigatório/clampado; falha de execução vira 422 e indisponibilidade do banco 503.
- `auth_user.password`, `idempotency_key`, `transacao_id` e tabelas internas do Django nunca entram no prompt nem podem ser projetadas. `enderecos_entrega` não existe no domínio: a pergunta retorna 422 em vez de inventar tabela.

## [1.20.0] - 2026-10-27 — Dashboard de Desempenho da API em Streamlit

### Adicionado
- **Instrumentação (Aula 20):** middleware `core.observability.RegistrarMetricasMiddleware` com medição de latência, normalização de paths, allow-list de rotas (`/api/`) e persistência em `core_requisicao_metrica`. Modelo e migração `0006_requisicaometrica`.
- **Cache por requisição:** janela *por thread* em `core.cache_metrics` (`iniciar_requisicao`/`finalizar_requisicao`), gravada nas colunas `cache_hits`, `cache_misses` e `cache_bypasses`. O painel exibe a hit rate real, com bypass fora do denominador.
- **Painel de desempenho:** página multipage `dashboard/pages/2_Desempenho_da_API.py` com KPIs (total, latência média/p95, taxa de erro e hit rate), gráficos temporais, distribuição por classe de status (2xx/3xx/4xx/5xx) com detalhe por código, requisições por endpoint, filtros interativos e `@st.cache_data(ttl=60)`.
- **Consultas seguras:** `dashboard/performance.py` com SQLAlchemy Core e bind parameters, agregações, validação de período e pedidos por status.
- **Retenção:** comando `manage.py limpar_metricas` (`--dias`, `--dry-run`) para podar o log de métricas.
- **Infra:** `API_METRICS_ENABLED` no compose/API e `dashboard` depende de `api: service_healthy`.
- **Testes:** `tests/unit/test_observability.py`, `tests/unit/test_dashboard_performance.py`, `tests/unit/test_cache_utils.py` (janela por requisição) e `tests/integration/test_api_metrics.py` (middleware, cache hit, toggle, poda).
- **Documentação:** `docs/aulas/20-desempenho.md`, README e `.env.example`.

### Corrigido
- Restaurados `api/core/models.py` e `api/core/serializers.py` da linha de base das Aulas 9–14 (a versão em edição havia perdido `idempotency_key`, `slug`, `is_active` e estados do pagamento). A Aula 20 acrescenta apenas `RequisicaoMetrica`.

## [1.19.0] - 2026-10-23 — Conexão Segura, SQL Injection e Painel Streamlit

### Adicionado

- **Conexão segura (Aula 19):** `dashboard/db.py` com montagem de URL via variáveis `DB_*`, engine SQLAlchemy com *pooling*, `pool_pre_ping`, *timeouts* (`connect_timeout`/`statement_timeout`) e `DB_SSLMODE=require`. PostgreSQL com TLS via imagem `docker/postgres/`.
- **Mitigação de SQL Injection:** `dashboard/queries.py` com SQLAlchemy Core e *bind parameters*; `dashboard/security.py` com allow-list para `ORDER BY`; simulação controlada em `dashboard/simular_sqli.py`.
- **Painel Streamlit:** `dashboard/app.py` com filtros dinâmicos (data, status, ID), ordenação segura, tabela, gráfico de barras, métricas e `@st.cache_data(ttl=60)`. *Live reload* com bind-mount e `runOnSave`.
- **Infraestrutura:** serviço `dashboard` no `docker-compose.yml`, Dockerfile e `.streamlit/config.toml`. `api`/`inventory`/`workers`/`tests` usam conexão com `sslmode=require` e variáveis `DB_*`.
- **Testes:** `tests/unit/test_dashboard_db.py`, `tests/unit/test_dashboard_queries.py`, `tests/unit/test_dashboard_sqli.py`, `tests/unit/test_inventory_database_aula19.py`.

### Alterado

- **README.md:** adicionada seção da Aula 19, serviço `dashboard` na tabela e URL do painel.
- **docs/aulas/19-dashboard.md:** documentação técnica da Aula 19.

## [1.14.1] - 2026-10-19 — Manutenção de otimização

> Passo de otimização do repositório: eliminação de duplicações entre os dois
> brokers, correções factuais e reorganização da documentação. Nenhum
> comportamento de runtime muda.

### Adicionado

- **Base comum de mensageria (`api/core/messaging/politica.py`,
  `excecoes.py`):** cabeçalhos de reentrega (`x-tentativa`, `x-evento-id`,
  `x-motivo`), leitura do contador, decisão da escada (`Destino`) e
  desserialização de corpo agora têm fonte única, compartilhada pelos
  consumidores AMQP (Aula 9) e Kafka (Aulas 10-11) — antes cada broker
  reimplementava o mecanismo. `MensagemIncorreta`/`FalhaInjetada` saem dos
  consumidores para `messaging.excecoes`, eliminando as duas definições
  paralelas em que um `except` do AMQP não capturava a exceção do Kafka.
- **`api/core/erros.py`:** implementação única de `descrever`; os caminhos
  `core.messaging.erros.descrever` e `core.llm.erros.descrever` passam a
  re-exportar (antes eram duas cópias idênticas).
- **`scripts/_medicao.py`:** `percentil` e `cabecalhos` compartilhados pelos
  scripts `measure_cache.py` e `measure_messaging.py` (antes, cópias).

### Corrigido

- **OpenAPI `1.14.0` → `1.14.1`:** o path do assistente era documentado como
  `/api/v1/assist` (sem barra final); a rota real — e a única testada — é
  `/api/v1/assist/`, como o resto das rotas Django do contrato.
- **`docker-compose.yml`:** o serviço de pagamentos interpolava
  `MESSAGERIA_LOG_LEVEL` enquanto código, `.env.example` e os demais
  serviços usam `MESSAGING_LOG_LEVEL` — na prática a variável era ignorada
  e o nível do logger sempre caía no default `INFO`.

### Mudado

- **Documentação:** o README (108 KB) virou um hub de ~11 KB; o conteúdo
  por aula foi para `docs/aulas/`, `docs/testes.md` e `docs/integrador.md`,
  e a Aula 7 foi fundida em `docs/autenticacao.md`. `PROMPTS_STUDY.md` foi
  para `docs/estudo/`.
- **Skills:** as 7 skills soltas de `.opencode/skills/` viraram 3 skills no
  formato `SKILL.md` (`arquitetura-e-squad`, `engenharia-devops`,
  `especialista-ia`); `AGENTS.md` na raiz guia os agentes.
- **Limpeza:** fixture órfã `relogio_fixo` e a dependência `freezegun`
  (não usada), stubs de spec, `.gitkeep`s, `node_modules` do `.opencode`,
  import morto `LlmResposta`, `SIMPLE_JWT` redundante nos test settings.

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