# Painel Analítico - Aula 19

## Objetivo

Implementar conexão segura com PostgreSQL (SSL/TLS, *pooling*, *timeouts*), consultas parametrizadas para mitigação de SQL Injection, painel Streamlit com filtros dinâmicos e *cache* (`@st.cache_data`), Docker Compose com *bind-mount* e *live reload*, além de TLS no banco.

## Arquitetura

```
dashboard/
├── app.py          # Painel Streamlit com filtros, tabela e gráfico
├── db.py           # Engine SQLAlchemy com pool/timeout/SSL
├── queries.py      # Consultas Core parametrizadas com allow-list
├── security.py     # Validação de status, ordenação e normalização
├── simular_sqli.py # Simulação controlada de SQL Injection
└── requirements.txt
```

## Variáveis de ambiente

```env
DB_HOST=db
DB_PORT=5432
DB_NAME=synapse
DB_USER=synapse
DB_PASSWORD=synapse
DB_SSLMODE=require
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=1800
DB_CONNECT_TIMEOUT=10
DB_STATEMENT_TIMEOUT_MS=30000
```

## Segurança da conexão

- **SSL/TLS obrigatório:** `DB_SSLMODE=require` (PostgreSQL com certificado autoassinado no serviço `db`).
- **Pooling:** `pool_size`, `max_overflow`, `pool_timeout`, `pool_recycle`, `pool_pre_ping`.
- **Timeouts:** `connect_timeout` e `statement_timeout` via `connect_args`.
- **Credenciais via ambiente:** sem *hardcode*.

## Prevenção a SQL Injection (Zero Interpolação)

- **Bind parameters:** `sqlalchemy.sql.select/where/in_` com valores parametrizados.
- **Allow-list para `ORDER BY`:** `dashboard/security.py` valida colunas e direção.
- **Sem interpolação de strings:** valores de filtros nunca são concatenados ao SQL.
- **Simulação:** `python -m dashboard.simular_sqli` trata payload malicioso como literal.

## Painel Streamlit

- Filtros: período (`date_input`), status (`multiselect`), ID do pedido (`text_input`).
- Ordenação segura por coluna permitida.
- Cache: `@st.cache_data(ttl=60)`.
- Visualização: `st.dataframe`, `st.bar_chart`, `st.metric`.

## Docker e live reload

- Serviço `dashboard` na porta `8501`.
- *Bind-mount* `./dashboard:/app/dashboard`.
- Configuração: `server.runOnSave=true`, `server.fileWatcherType=poll`.
- Banco com TLS via `docker/postgres/`.

## Execução

```bash
docker compose up -d --build
# Painel: http://localhost:8501
# Simulação SQLi:
docker compose run --rm dashboard python -m dashboard.simular_sqli
```

## Testes

```bash
docker compose run --rm tests
```
