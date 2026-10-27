# Spec: Dashboard de Desempenho da API em Streamlit (Aula 20)

## 1. Objetivo

Desenvolver e disponibilizar um Painel de Observabilidade/Desempenho em Streamlit, integrado à infraestrutura do mini-backend de pedidos (desenvolvido na Aula 11). O painel deve consumir, tratar e exibir graficamente as métricas de performance da API, incluindo tempos de resposta, throughput, taxas de sucesso/erro e utilização de cache/mensageria.

## 2. Contexto

No ecossistema do SynapseShop, a observabilidade é fundamental para acompanhar a performance dos microserviços em produção. Nesta etapa, utilizando a base construída na Aula 11 (API de pedidos com cache em Redis e/ou mensageria com RabbitMQ/Kafka), será criada uma camada de visualização em Streamlit dedicada à análise de métricas operacionais e de latência da API.

## 3. Requisitos de Entrega (Definition of Done)

[x] Aplicação Streamlit Funcional: O dashboard de desempenho deve ser iniciado e executado corretamente em ambiente conteinerizado.
[x] Métricas Principais Visualizadas:
    [x] Indicadores de Desempenho (KPIs): Exibição de total de requisições, latência média (ms) / p95 e taxa de erro (%) via componentes 
    [x] Gráfico de Latência / Throughput: Visualização temporal de requisições por minuto/segundo ou tempo de resposta por endpoint.  
    [x] Distribuição de Status Codes: Gráfico (barras ou pizza) detalhando as respostas da API (2xx, 4xx, 5xx).
[x] Filtros Interativos: O painel deve conter pelo menos dois filtros funcionais (ex.: seleção por período/data, endpoint específico ou status code).
[x] Otimização de Consultas: Utilização do decorator @st.cache_data para otimizar o carregamento das métricas sem sobrecarregar a infraestrutura.   
[x] Integração no Docker Compose: O serviço do app Streamlit deve estar configurado no docker-compose.yml para rodar junto com a stack da API da Aula 11.
[x] Documentação Atualizada:
    [x] O arquivo README.md deve ser atualizado com as instruções de como subir e acessar o dashboard de métricas.
    [x] O arquivo PROMPTS.md deve registrar os prompts de IA generativa utilizados para auxiliar no desenvolvimento dos gráficos e layouts em Streamlit.
[x] Isolamento de Escopo: Garantir que nenhuma dependência ou código relativo às Aulas 21+ seja introduzido.

## 4. Evidências de validação

- `docker compose run --rm tests` → **281 passed**, cobertura **88,97%** (gate 85%).
- `docker compose run --rm tests python api/manage.py check` → sem problemas.
- `docker compose run --rm tests python api/manage.py makemigrations --check --dry-run`
  → `No changes detected`.
- `docker compose up -d --build api dashboard` → migração
  `core.0006_requisicaometrica` aplicada; `api` e `dashboard` saudáveis.
- Duas chamadas a `GET /api/v1/items/` geraram duas linhas em
  `core_requisicao_metrica`: a primeira com `cache_misses=1` (168,9 ms) e a
  segunda com `cache_hits=1` (2,7 ms). `/health` não gerou linha.
- `docker compose exec dashboard python -c "..."` confirmou as consultas reais
  no PostgreSQL: endpoints, resumo, classes `2xx` e pedidos por status.
- `docker compose exec api python api/manage.py limpar_metricas --dias 30 --dry-run`
  → comando operacional disponível.
- `python -m ruff check .` → sem erros.