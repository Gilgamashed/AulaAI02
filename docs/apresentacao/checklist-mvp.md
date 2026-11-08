# Checklist do MVP — SynapseShop

Matriz de verificação do Definition of Done da apresentação final (Aula 25).
Cada linha liga o requisito original à implementação, ao teste automatizado e
à evidência que pode ser reproduzida em execução.

Status possíveis: **ATENDIDO**, **PARCIAL** ou **PENDENTE**.

| # | Requisito | Implementação | Testes | Evidência em execução | Status |
| - | --------- | ------------- | ------ | --------------------- | ------ |
| 1 | Cadastro e listagem de produtos com cache no catálogo | `api/core/views.py` (`ItemViewSet`), `api/core/cache.py`, `api/core/models.py` | `tests/integration/test_catalog_lifecycle.py`, `tests/unit/test_cache_utils.py`, `tests/integration/test_api_metrics.py` | `GET /api/v1/items/` duas vezes + `GET /api/v1/cache/metrics/`; passo 4 do `validar_mvp.py` | ATENDIDO |
| 2 | Criação de pedidos com publicação de `PedidoCriado` | `api/core/views.py` (`PedidoViewSet.create`), `api/core/messaging/contracts.py`, `docs/contracts/pedido_criado.md` | `tests/integration/test_pedidos_pagamento_fluxo.py`, `tests/unit/test_contracts_pedido.py` | `POST /api/v1/pedidos/` com `Idempotency-Key`; resposta traz o bloco `evento`; passo 5 do `validar_mvp.py` | ATENDIDO |
| 3 | Pagamento e notificação assíncronos com idempotência e DLQ | `api/core/messaging/consumidor.py`, `kafka_consumidor.py`, `dedupe.py`, `api/core/models.py` | `tests/unit/test_messaging_politica.py`, `tests/unit/test_notificacoes.py`, `tests/integration/test_pedidos_pagamento_fluxo.py` | `POST /api/v1/pedidos/{id}/pagamento/`, polling do pagamento e `GET /api/v1/notificacoes/?pedido={id}`; passes 7 e 8 do `validar_mvp.py`; DLQ com `X-Simular-Falha` e `inspecionar_dlq_kafka` | ATENDIDO |
| 4 | Autenticação JWT com papéis de administrador e cliente | `api/config/settings.py`, `api/core/urls.py`, `api/core/permissions.py`, `docs/autenticacao.md` | `tests/integration/test_auth_throttling.py`, `tests/integration/test_catalog_lifecycle.py` | Login de `demo_admin` e `demo_user`; `403` nas rotas administrativas para `user`; passo 2 do `validar_mvp.py` | ATENDIDO |
| 5 | Assistente de suporte via IA com engenharia de prompt | `api/core/llm/`, `api/core/views.py` (`AssistView`) | `tests/unit/test_llm_resiliencia.py`, `tests/unit/test_assist_serializer.py`, `tests/integration/test_assist_endpoint.py` | `POST /api/v1/assist/`; passo 9 do `validar_mvp.py` | ATENDIDO |
| 6 | Consulta de dados de negócio em linguagem natural (texto-para-SQL) | `api/core/ask_sql/`, `api/core/views.py` (`AskSqlView`), `dashboard/ask_sql.py` | `tests/unit/test_ask_sql_*.py`, `tests/integration/test_ask_sql_endpoint.py` | `POST /api/v1/ask_sql/`; passo 10 do `validar_mvp.py` | ATENDIDO |
| 7 | Assistente de documentação (RAG) com citação de fontes | `api/core/ask_docs/`, `api/core/management/commands/indexar_docs.py` | `tests/unit/test_ask_docs_*.py`, `tests/integration/test_ask_docs_endpoint.py` | `POST /api/v1/ask_docs/` com `sources` não vazio; passo 11 do `validar_mvp.py` | ATENDIDO |
| 8 | Dashboards de vendas e de desempenho da API | `dashboard/app.py`, `dashboard/queries.py`, `dashboard/performance.py`, `dashboard/pages/` | `tests/unit/test_dashboard_queries.py`, `tests/unit/test_dashboard_sales.py`, `tests/unit/test_dashboard_performance.py` | Streamlit em `http://localhost:8501` (receita, ticket médio, receita/dia, top produtos e latência da API); `GET /_stcore/health` no `validar_mvp.py` | ATENDIDO |
| 9 | Suíte de testes automatizados e documentação completa da API | `tests/`, `pyproject.toml` (gate de 85%), `docs/openapi.yaml`, Swagger/ReDoc | Toda a suíte (`pytest`); `ruff check .`; `mypy api services dashboard` | `docker compose run --rm tests`; `/docs/`, `/redoc/` e `/docs/openapi.yaml` | ATENDIDO |
| 10 | Pipeline de CI/CD | `.github/workflows/ci.yml`, `.github/compose.ci.yml`, `scripts/validar_compose.py` | Jobs `test-and-lint`, `docker-build`, `compose-smoke` e `publish` | Execução verde no GitHub Actions; `python scripts/validar_compose.py` local | ATENDIDO |

## Limitações conhecidas

- **Provedores de IA:** o padrão é `LLM_PROVIDER=auto`: Gemini preferencial e
  mock como fallback apenas para indisponibilidade técnica, depois de esgotar
  retry/breaker. `gemini` é estrito e `mock` é determinístico; o mock continua
  sendo o padrão de testes/CI (spec `spec_da_aula_25_gemini.md`).
- **RAG lexical:** os embeddings são TF-IDF locais, sem modelo neural.
  Sinônimos que não compartilham tokens podem não ser recuperados; o guardrail
  responde `sources: []` nesses casos. Um modelo de embeddings Gemini é
  evolução futura.
- **Dashboard de desempenho:** as métricas de cache e de requisição são do
  processo que atende a chamada (gunicorn com um worker por padrão). O painel
  mede latência, status e hit rate da API, mas **não** mede profundidade de
  fila nem lag do broker — para isso existem `docker compose logs` e
  `inspecionar_dlq_kafka`.
- **Front-end:** `/app/` é um mock de apresentação (HTML/CSS/JS inline), não
  um produto de produção. Não há build, framework SPA, acessibilidade
  certificada nem testes de navegador.
- **Deploy:** o job `publish` publica a imagem no DockerHub como **deploy
  simulado**; não há provisionamento de ambiente real.

## Como reproduzir as evidências

```bash
# 1. Stack
docker compose up -d --build

# 2. Usuários, massa demo e índice RAG
docker compose exec api python api/manage.py seed_auth
docker compose exec api python api/manage.py seed_demo
docker compose exec api python api/manage.py indexar_docs

# 3. Smoke ponta a ponta (12 passos)
python scripts/validar_mvp.py

# 4. Sem os passos de IA (marcados como SKIP)
python scripts/validar_mvp.py --skip-ai

# 5. Suíte, lint e tipos
docker compose run --rm tests
python -m ruff check .
python -m mypy api services dashboard

# 6. Comunicação entre serviços do Compose
python scripts/validar_compose.py
```

Roteiro narrativo da apresentação:
[roteiro-demo.md](roteiro-demo.md).
