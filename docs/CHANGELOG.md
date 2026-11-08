# Changelog

Todas as alterações relevantes do projeto SynapseShop. O formato segue o
[*Keep a Changelog*](https://keepachangelog.com/pt-BR/1.1.0/) e o versionamento
é [SemVer](https://semver.org/lang/pt-BR/). O ficheiro foi criado na Aula 13 e
codifica retroativamente o histórico das aulas anteriores.

## [1.25.1] - 2026-11-08 — Fallback automático Gemini → mock

### Adicionado
- **`LLM_PROVIDER=auto` como padrão:** Gemini é o provedor preferencial; o mock especializado da tarefa assume apenas em indisponibilidade técnica. `gemini` continua estrito (sem fallback) e `mock` continua determinístico.
- **Fallback no `LlmService`:** erros recuperáveis (timeout, conexão/DNS, 429, 5xx) caem para o mock depois de esgotar retry/breaker; erros terminais de disponibilidade (401/403/404) caem após a primeira falha. Erro 400 e bloqueio de segurança **não** fazem fallback.
- **Novas exceções:** `LlmModeloIndisponivel` (HTTP 404) e `RespostaBloqueada` (bloqueio de segurança com motivo), permitindo separar disponibilidade de conteúdo bloqueado.
- **Métricas de fallback:** `fallbacks`, `fallback_sucessos`, `fallback_falhas`, `fallback_tokens_*`, `fallback_custo_usd`, `provedor_configurado`, `provedor_efetivo`, `ultimo_motivo_fallback` e `fallback_ativo` em `/api/v1/llm/metrics/`.
- **Front-end:** o cartão de IA mostra provedor configurado, provedor efetivo, modelo e estado do fallback, além do JSON detalhado.
- **Testes:** `tests/unit/test_llm_fallback.py` cobre fallback por tarefa, 400/bloqueio sem fallback, circuito aberto, credencial/modelo inválidos e falha do próprio fallback; `test_llm_gemini.py`, `test_llm_metricas.py`, `test_assist_endpoint.py` e `test_app_frontend.py` foram ampliados.

### Alterado
- **`api/config/settings.py`, `.env.example` e `docker-compose.yml`:** default `auto`, timeout de 30 s no exemplo real e `LLM_MAX_TENTATIVAS=2` para reduzir a espera antes do fallback; o serviço `tests` continua fixando `mock`.
- **`api/core/llm/gemini.py`:** 404 vira `LlmModeloIndisponivel`; bloqueio de segurança vira `RespostaBloqueada`; resposta vazia continua `RespostaInvalida`.
- **`api/core/llm/servico.py`:** resolução de `auto`, fallback task-specific e `modelos_efetivos` coerente com a chave.
- **`api/core/views.py`:** novos campos de métricas mantendo `provedor` e `modelo` por compatibilidade.
- **`api/core/templates/core/app.html` e testes do front-end:** filtro `is_active` no catálogo, `AbortController`/timeout no refresh do JWT e aviso explícito de DLQ no pagamento.
- **`docs/openapi.yaml`:** versão `1.25.1` e schema `LlmMetrics` com os campos de fallback.
- **`docs/aulas/25-ia-real-gemini.md`, `README.md`, `docs/apresentacao/roteiro-demo.md`, `docs/apresentacao/checklist-mvp.md`, `AGENTS.md` e `PROMPTS.md`:** documentam `auto`, fallback, modos estritos e diagnóstico.

### Notas
- **Latência:** como o fallback ocorre depois de retry/breaker, o exemplo usa `LLM_MAX_TENTATIVAS=2`; com timeout de 30 s e 3 tentativas, a primeira resposta pode demorar.
- **Validação real:** a chave do `.env` respondeu com `gemini-3.5-flash` (20 tokens de entrada/1 de saída); `auto` respondeu 200 nos três endpoints; um modelo inexistente disparou fallback para o mock com `fallbacks=1`, `provedor_efetivo=mock` e `fallback_ativo=true`.
- **Gate:** **553 testes**, cobertura **90,21%**, `ruff check .` e `mypy api services dashboard` verdes; nenhum teste automatizado depende de rede ou da chave real.

## [1.25.0] - 2026-11-08 — Fechamento do MVP, Demo e IA Real (Gemini)

### Adicionado
- **Mock de front-end em `GET /app/` (Aula 25):** página única servida pelo Django, same-origin, com HTML/CSS/JS inline e sem build, CORS ou container novo. Cobre login/logout com JWT em `sessionStorage`, refresh automático em `401`, catálogo com busca/filtro/ordenação e CRUD por papel, carrinho com `Idempotency-Key` e reenvio idempotente, pagamento com polling/notificações, abas de IA (`/assist/`, `/ask_sql/`, `/ask_docs/`), cartões de saúde/cache/métricas e links para Streamlit/Swagger/ReDoc/OpenAPI. O checkbox de DLQ só é renderizado com `DEBUG=True`; dados da API entram via `textContent`/DOM, nunca `innerHTML`.
- **View `AppFrontendView` e rota `app/`:** template `api/core/templates/core/app.html`; a `GEMINI_API_KEY` permanece restrita ao processo do servidor.
- **Provedor Gemini real:** `api/core/llm/gemini.py` (`ProvedorGemini`) implementa a porta `ProvedorLlm` com `google-genai`, cliente injetável, modelo padrão `gemini-3.5-flash`, mapeamento de erros (`401/403` → configuração inválida, `400/404` → cliente, `429` → rate limit com `retry_after`, `5xx` → servidor, timeout/conexão e resposta vazia) e import tardio do SDK. O adaptador envia `thinking_config.thinking_budget=0` para manter a latência previsível e impedir que tokens de raciocínio consumam `max_output_tokens`. Também inspeciona `finish_reason` e `prompt_feedback.block_reason`, convertendo bloqueios de segurança/conteúdo em `RespostaInvalida` (HTTP 502). A resiliência (timeout, retry com backoff+jitter, circuit breaker e métricas) continua em `LlmService`.
- **Telemetria com modelo efetivo:** `modelos_efetivos()` resolve, sem instanciar cliente, o modelo realmente usado por `assist`, `sql` e `docs` (inclusive a troca de `mock*` por `gemini-3.5-flash`). `GET /api/v1/llm/metrics/` mantém `modelo` (assist) e passa a expor `modelos: {assist, sql, docs}`.
- **Qualidade de tipos no gate:** `pyproject.toml` configura mypy com `mypy_path`, plugin do Django e stubs de Django/DRF; `requirements-dev.txt` fixa `mypy`, `django-stubs`, `django-stubs-ext` e `djangorestframework-stubs`; o CI executa `mypy api services dashboard`.
- **Seleção por `LLM_PROVIDER=mock|gemini`:** `criar_llm_service` mantém mocks como padrão e singletons/breakers independentes por tarefa; valores desconhecidos falham com `LlmConfiguracaoInvalida`. Não há fallback automático — o plano B é trocar explicitamente para `mock`.
- **Comando `manage.py seed_demo`:** massa idempotente com 4 categorias, 12 produtos ativos, 20 pedidos históricos nos últimos 30 dias, 14 pagamentos (12 aprovados/2 recusados) e 14 notificações; exige `seed_auth`, aceita `--silent` e não apaga dados existentes.
- **Dashboard de vendas:** `dashboard/queries.py` lê a coluna JSON `itens`, traduz SKUs pelo catálogo e agrega receita total, ticket médio, pedidos processados, receita por dia e produtos mais vendidos (quantidade e receita), apenas para pedidos `processado`. `dashboard/app.py` exibe os indicadores, mantendo filtros, ordenação segura, limite e cache de 60 s.
- **Smoke ponta a ponta `scripts/validar_mvp.py`:** 12 passos com biblioteca padrão (saúde API/inventory, login dos dois usuários, cache, pedido, idempotência, pagamento, worker/notificação, três recursos de IA, `/app/` e dashboard), `--skip-ai`, timeouts configuráveis, resumo JSON (`ok`, `passos`, `skipped`, `falhas`) e exit code diferente de zero em falha obrigatória.
- **Documentação de apresentação:** `docs/apresentacao/checklist-mvp.md` (matriz dos dez itens do MVP com implementação, testes, evidência, status e limitações), `docs/apresentacao/roteiro-demo.md` (ordem, tempos e planos B) e `docs/aulas/25-ia-real-gemini.md` (arquitetura, configuração, testes, troubleshooting e limitações).
- **Testes:** `tests/unit/test_llm_gemini.py` (22 casos), `tests/unit/test_seed_demo.py` (7), `tests/unit/test_dashboard_sales.py` (6), `tests/unit/test_validar_mvp.py` (5) e `tests/integration/test_app_frontend.py` (3); a suíte completa fecha em **532 testes**.

### Alterado
- **`requirements.txt`:** `google-genai>=1.0,<2.0`.
- **`api/config/settings.py`:** `GEMINI_API_KEY`; a fábrica usa `LLM_PROVIDER` e os modelos por tarefa.
- **`.env.example`, `docker-compose.yml` e `.env` local:** documentam/plumbam `GEMINI_API_KEY`, `LLM_PROVIDER` e modelos; o serviço `tests` força `LLM_PROVIDER=mock` e chave vazia para nunca chamar a API real.
- **`api/config/urls.py` e `api/core/views.py`:** rota e view do mock de front-end; a view do `/assist/` pede resposta em português do Brasil.
- **`api/core/ask_docs/prompt.py`:** regras no `system` e contexto na mensagem `user`, com instrução explícita de tratar o CONTEXTO como dado não confiável e ignorar instruções contidas nele.
- **`docs/openapi.yaml`:** versão `1.25.0`; `LlmMetrics` ganhou `modelos` (modelo efetivo por tarefa).
- **`README.md`:** `seed_demo`, `/app/`, smoke do MVP, configuração Gemini, seção da Aula 25 e índice de aulas.
- **`AGENTS.md`:** comandos do `seed_demo`/`validar_mvp`, estrutura do front-end, regra de IA mock/Gemini e gate de tipos.
- **`dashboard/app.py` e `dashboard/queries.py`:** indicadores de vendas da Aula 25.
- **`api/config/settings.py`, `.env.example`, `README.md` e `docs/aulas/25-ia-real-gemini.md`:** timeout sugerido de 30 s para o Gemini real (o prompt de SQL é o mais longo) e custos de exemplo `0.30/2.50` por 1M de tokens.
- **`requirements-dev.txt`, `pyproject.toml` e `.github/workflows/ci.yml`:** dependências, configuração e etapa de mypy.
- **`dashboard/performance.py`:** anotação de tipo na consulta de endpoints.

### Corrigido
- **`finish_reason` bloqueado:** respostas com `SAFETY`, `RECITATION`, `BLOCKLIST`, `PROHIBITED_CONTENT`, `SPII` e correlatos viram `RespostaInvalida`, mesmo que tragam texto parcial.
- **Métricas do modelo efetivo:** `/api/v1/llm/metrics/` não reporta mais `mock` quando `LLM_PROVIDER=gemini` e `LLM_MODEL` ainda está no default.
- **Prompt injection no RAG:** o contexto deixou de ser enviado como instrução de sistema; os testes cobrem um trecho malicioso.
- **Vazamento em logs:** teste com `caplog` garante que a chave não aparece em exceções nem em logs.
- **Latência do `/ask_sql/`:** a validação real mostrou 503 com 20 s/1 tentativa e 200 com 30 s/2 tentativas; a recomendação e o exemplo do `.env` passaram a 30 s.

### Notas
- O mock continua sendo o padrão de testes/CI e o plano B da apresentação; nenhum teste automatizado depende de rede ou da chave real.
- O `gemini-2.5-flash`, sugerido na primeira versão da aula, foi aposentado para chaves novas durante a validação (HTTP 404). O padrão passou a ser `gemini-3.5-flash`.
- Validação real final: `/assist/`, `/ask_sql/` e `/ask_docs/` responderam **200** com `LLM_PROVIDER=gemini`; o `/ask_sql/` gerou SQL válido e as métricas mostraram `modelos={assist,sql,docs}=gemini-3.5-flash`.
- Gate local/CI: **532 testes**, cobertura **90,03%**, `ruff check .` e `mypy api services dashboard` verdes.
- Os embeddings do RAG continuam lexicais (TF-IDF), sem modelo neural.
- O deploy permanece simulado e `/app/` é um mock de demonstração, não um front-end de produção.

## [1.24.0] - 2026-11-06 — Assistente de Documentação com RAG

### Adicionado
- **Pacote `api/core/ask_docs/` (Aula 24):** pipeline completo de RAG — chunking (~400 tokens, overlap de ~80), embeddings locais determinísticos, índice SQLite, recuperação por cosseno (`top_k`/`min_score`), montagem do prompt e guardrail.
- **Índice SQLite leve:** tabelas `documents` (`doc_id`, `path`, `title`, `hash`, `indexed_at`) e `chunks` (`chunk_id`, `doc_id`, `chunk_text`, `start`, `end`, `embedding` BLOB, `dim`), mais a tabela interna `vocabulario` (`term`, `idf`, `indice`) para vetorizar a pergunta com os mesmos pesos do corpus.
- **Endpoint `POST /api/v1/ask_docs/`:** recebe `{question, top_k, min_score}`, valida a entrada e devolve `{answer, sources:[{path,title,range,score}]}`. Restrito ao papel `admin` (`IsAuthenticated` + `IsAdminRole`).
- **Comando `manage.py indexar_docs`:** ingestão das fontes (`README.md` e `docs/openapi.yaml` por padrão), idempotente por hash, com `--force`, `--root`, `--index-path` e `--source`.
- **Provedor `ProvedorMockDocs`:** resposta extrativa determinística na mesma porta `ProvedorLlm`, selecionada por `criar_llm_service(tarefa="docs")`; sempre cita o bloco recuperado.
- **Volume `rag_data` no Compose:** preserva `/app/data/rag_index.sqlite3` entre recriações; a ingestão roda no startup após `migrate`.
- **Testes:** 63 testes unitários (chunking, embeddings, índice, ingestão, serviço e prompt/mock) e testes de integração HTTP cobrindo 401/403/400, caminho feliz, guardrail e mapeamento 500/502/503.
- **`docs/aulas/24-rag-documentacao.md`:** arquitetura, modelagem, ingestão, recuperação, contrato, testes e limitações.

### Alterado
- **`api/config/settings.py`:** `ASK_DOCS_*` (índice, fontes, `top_k`, `min_score`, chunking, tokens e log), `LLM_MODEL_DOCS` e o logger `core.ask_docs`.
- **`api/core/llm/servico.py`:** fábrica por tarefa agora também aceita `docs`, com singleton e circuit breaker próprios.
- **`api/core/urls.py`:** rota `ask_docs/` sob `/api/v1/`.
- **`docs/openapi.yaml`:** versão `1.24.0`, tag `ask_docs`, path `/api/v1/ask_docs/` e schemas `AskDocsRequest`, `AskDocsSource` e `AskDocsResponse`.
- **`README.md`:** rota, índice de aulas e seção do assistente RAG com arquitetura, parâmetros de indexação, reindexação, exemplos e limitações.
- **`.env.example`, `.gitignore`, `.dockerignore`, `Dockerfile` e `docker-compose.yml`:** variáveis da Aula 24, exclusão do SQLite local, `indexar_docs` no startup e volume dedicado.
- **`specs/README.md` e `AGENTS.md`:** índice da Aula 24 e comandos de indexação/simulação.

### Notas
- Os embeddings são **lexicais** (TF-IDF com vocabulário exato), sem rede ou credenciais; sinônimos sem tokens em comum podem não se aproximar. O índice e a recuperação são reais; a síntese é o mock extrativo documentado.
- Perguntas fora do limiar não chamam a LLM: recebem a frase de guardrail e `sources: []`.

## [1.23.0] - 2026-11-04 — Pipeline de CI/CD Avançado: Cache, Compose e Deploy Simulado

### Adicionado
- **Cache de dependências Python (Aula 23):** `actions/setup-python@v5` com `cache: pip` e `cache-dependency-path` cobrindo `requirements.txt`, `requirements-dev.txt`, `services/inventory/requirements.txt` e `dashboard/requirements.txt`.
- **Cache de camadas Docker:** `docker/setup-buildx-action@v3` + `docker/build-push-action@v6` com `cache-from/cache-to: type=gha` e `mode=max`, no escopo compartilhado `synapseshop-api` entre os jobs de build, integração e publicação.
- **Job `compose-smoke`:** constrói a imagem da API com cache, carrega `synapseshop-api:ci`, sobe `db`, `api` e `dashboard` com `docker compose up -d --wait` e valida a comunicação entre os serviços.
- **Script `scripts/validar_compose.py`:** smoke test com cinco caminhos (host→API, host→dashboard, API→PostgreSQL, dashboard→PostgreSQL e dashboard→API), diagnóstico automático de `ps`/logs e execução multiplataforma (stdlib).
- **Override `.github/compose.ci.yml`:** aponta a API para a imagem pré-construída e remove o `build` com `!reset null`, reaproveitando o cache GHA.
- **Job `publish` (deploy simulado):** login com `docker/login-action@v3`, tags via `docker/metadata-action@v5` (`sha-<completo>`, branch e `latest` no branch padrão), push com `docker/build-push-action@v6`, verificação do digest com `imagetools inspect` e resumo no `$GITHUB_STEP_SUMMARY`.
- **Guarda de segredos:** ausência de `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN` gera warning e publicação ignorada, mantendo PRs e forks verdes.
- **Cache mount do pip no `dashboard/Dockerfile`**, alinhando o painel ao padrão de cache dos demais Dockerfiles.

### Alterado
- **`.github/workflows/ci.yml`:** gatilhos mantidos; adicionados `concurrency` (cancela apenas PRs antigos), `docker-build` com Buildx/cache, `compose-smoke` com `needs: docker-build` e `publish` com `needs` dos três jobs anteriores.
- **`README.md`:** seção de CI/CD reescrita para o estado das Aulas 22–23 (cache, Compose, DockerHub, segredos, monitorização, rollback e comandos locais).
- **`specs/README.md`:** índice da Aula 23.
- **`AGENTS.md`:** comando de smoke do Compose e validação correspondente.

### Corrigido
- **TLS do PostgreSQL em volume novo (Aula 19, exposto pelo job `compose-smoke`):** `docker/postgres/init-ssl.sh` gerava o certificado com `-key` (que tenta ler uma chave existente) em vez de `-newkey`/`-keyout`; em um volume recém-criado o `openssl` falhava, o `ssl` ficava desligado e a API morria com `server does not support SSL, but SSL was required`. O script agora gera a chave corretamente e é idempotente.
- **Certificados dentro do `PGDATA`:** antes ficavam em `/var/lib/postgresql/certs`, fora do volume — recriar o container apagava os arquivos e o `postgresql.conf` persistido apontava para chaves inexistentes. Agora ficam em `$PGDATA/certs` e sobrevivem à recriação.
- **Wrapper de entrypoint (`docker-entrypoint-wrapper.sh`):** garante TLS em todo start, inclusive em volumes já inicializados (onde o `/docker-entrypoint-initdb.d` não roda) e em volumes de versões anteriores com caminhos antigos; reescreve o bloco TLS e as linhas `hostssl` em vez de só anexar. O `CMD ["postgres"]` foi redeclarado porque definir `ENTRYPOINT` zera o `CMD` herdado da imagem base.

### Documentação
- **`docs/aulas/23-ci-cd-avancado.md`:** arquitetura dos jobs, estratégia de cache, serviços do Compose, deploy simulado, cadastro de segredos, monitorização, tabela de falhas propositadas e rollback por tag.
- **`PROMPTS.md`:** registro do uso de IA na especificação e implementação da Aula 23.

### Notas
- O `!reset` do override exige Docker Compose >= 2.24.4.
- O deploy continua simulado: a imagem é publicada no DockerHub, mas nenhum ambiente de produção é provisionado.
- Apenas a imagem da API é publicada; dashboard e inventory são construídos somente no Compose.

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