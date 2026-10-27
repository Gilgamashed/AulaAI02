# Dashboard de Desempenho da API (Aula 20)

## Objetivo

Criar um painel de observabilidade/desempenho no Streamlit para acompanhar
latência, throughput, taxas de sucesso/erro e utilização de cache da API,
sem introduzir dependências de aulas posteriores.

## Instrumentação

- Middleware `core.observability.RegistrarMetricasMiddleware`, registrado no
  fim de `MIDDLEWARE` (mais próximo da view).
- Mede a latência com `time.perf_counter()` e grava uma linha em
  `core_requisicao_metrica` por requisição atendida sob `/api/`.
- Fora do escopo da amostra: `/health` (healthcheck a cada 10 s), `/admin`,
  `/static`, `/docs` e `/redoc`.
- Paths normalizados (`/api/v1/items/42/` → `/api/v1/items/{id}/`) para
  reduzir a cardinalidade de endpoints. IDs numéricos e UUIDs são cobertos.
- Exceções não tratadas viram uma linha com `status_code=500` e são
  repropagadas. Falhas ao gravar a métrica são logadas em `debug` e **não**
  derrubam a requisição.
- Toggle `API_METRICS_ENABLED` (padrão `true`).

### Métricas de cache

O coletor `core.cache_metrics` (Aula 8) ganhou uma janela *por thread*:

1. o middleware chama `iniciar_requisicao()` antes da view;
2. cada `cache_aside` continua alimentando os contadores globais e, se a
   janela estiver aberta, também os contadores da requisição;
3. ao final, `finalizar_requisicao()` devolve `hits`, `misses` e `bypasses`,
   que são gravados na mesma linha da métrica.

Com isso a *hit rate* do dashboard é medida (`hits / (hits + misses)`), não
uma estimativa baseada em latência. `bypass` fica fora do denominador, como
na métrica original da Aula 8.

Limite conhecido: os contadores são por processo. O Compose usa 1 worker do
gunicorn, então a leitura é exata; com múltiplos workers, cada processo grava
a sua parte e o dashboard soma as linhas.

## Painel

- Página multipage: `dashboard/pages/2_Desempenho_da_API.py`.
- Consultas: `dashboard/performance.py`, SQLAlchemy Core com bind parameters.
- Filtros: período (data inicial/final), endpoint e classe de status
  (2xx/3xx/4xx/5xx).
- KPIs: total, latência média, p95, erros, taxa de erro e cache hit rate.
- Gráficos: throughput por hora, latência média/p95 por hora, distribuição
  por classe de status (com detalhe por código) e requisições por endpoint.
- Cache Streamlit: `@st.cache_data(ttl=60)` nas consultas.
- Bloco de pedidos: foto de `core_pedido` por status. **Não** é
  profundidade de fila do broker.

## Retenção

A tabela é um log operacional e cresce a cada requisição. O comando abaixo
mantém os últimos 30 dias:

```bash
docker compose exec api python api/manage.py limpar_metricas --dias 30
```

`--dry-run` mostra quantas linhas seriam removidas sem apagar. O comando pode
ser agendado no host (cron/Task Scheduler).

## Execução

```bash
docker compose up -d --build
```

A migração `0006_requisicaometrica` é aplicada pelo serviço `api` no startup.
Acesse [http://localhost:8501](http://localhost:8501), selecione **Desempenho
da API** e gere tráfego em `/api/v1/items/`.

Para reconstruir apenas o necessário:

```bash
docker compose up -d --build api dashboard
```

## Testes

- `tests/unit/test_observability.py`: normalização de path e allow-list de
  rotas instrumentadas.
- `tests/unit/test_dashboard_performance.py`: agregações, p95, classes de
  status, hit rate e consultas parametrizadas em SQLite.
- `tests/unit/test_cache_utils.py`: janela de cache por requisição.
- `tests/integration/test_api_metrics.py`: middleware, toggle, cache hit real,
  rotas ignoradas, falha de gravação e poda por retenção.

## Limitações e decisões

- A gravação é síncrona e acontece depois da resposta ao cliente. Em troca de
  simplicidade, cada request faz um `INSERT`; a retenção controla o volume.
- A latência medida começa depois dos middlewares acima do de métricas
  (segurança/sessão), por ele estar no fim da pilha. O objetivo é medir o
  trabalho da aplicação, não o overhead do framework.
- Endpoints com slugs arbitrários (fora de `/api/`) não são normalizados
  porque essas rotas não são instrumentadas.
- Não há métricas de fila do broker: os contadores do consumidor vivem no
  processo do worker e não são expostos por HTTP (decisão da Aula 9). O bloco
  do painel mostra o estado persistido dos pedidos e diz isso explicitamente.
