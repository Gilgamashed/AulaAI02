## [2026-10-23] Aula 19 - Conexão Segura, SQL Injection e Painel Streamlit

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec `specs/spec_da_aula_19.md` - implementar conexão segura com PostgreSQL (SSL/TLS, pooling, timeouts), mitigar SQL Injection com consultas parametrizadas e allow-list, criar painel Streamlit com filtros/cache, integrar ao Docker Compose com live reload e TLS no banco.
- **Prompt:** "vamos prosseguir agora com a realização de todas as tarefas e responsabilidades do @specs/spec_da_aula_19.md para validação pelo DoD. podemos incluir testes agora. não commitar por enquanto. lembrando que estou usando o windows powershell, por isso comandos como 'tail' e 'head' não funcionam e geram erro. utilize comandos nativos do powershell."
- **Resultado/Decisão:** Criado `dashboard/` com `db.py`, `security.py`, `queries.py`, `simular_sqli.py`, `app.py`, Dockerfile e config. Adicionado TLS ao PostgreSQL via `docker/postgres/`. Atualizados `docker-compose.yml`, `api/config/settings.py`, `services/inventory/app/config.py`, `services/inventory/app/database.py`. Removidos módulos parciais `api/core/db/` e `scripts/db/`. Criados testes unitários para conexão segura, consultas parametrizadas, simulação SQLi e inventory. Atualizados `README.md`, `docs/aulas/19-dashboard.md`, `docs/CHANGELOG.md`, `specs/README.md`, `AGENTS.md`, `pyproject.toml` e `.env.example`.
- **Revisão humana/ajuste manual:** Zero interpolação de strings em SQL, ordenação restrita a allow-list, uso exclusivo de bind parameters, `DB_SSLMODE=require` no compose, cache `@st.cache_data(ttl=60)` e bind-mount com live reload. Não commitado conforme solicitado.

## [2026-10-27] Aula 20 - Dashboard de Desempenho da API em Streamlit

- **Ferramenta:** opencode (opencode/big-pickle) e OpenCode (DeepSeek V4.1 Flash) na revisão/correção.
- **Contexto:** Spec `specs/spec_da_aula_20.md` - criar painel de observabilidade/desempenho com KPIs, latência/p95, throughput, distribuição por status code, filtros interativos, cache, integração ao Docker Compose.
- **Prompt 1 (implementação inicial):** "vamos prosseguir agora com a realização de todas as tarefas e responsabilidades do @specs/spec_da_aula_20.md para validação pelo DoD. vamos seguir a spec para que os itens do DoD sejam concluidos."
- **Prompt 2 (revisão do DoD):** "Poderia verificar se está tudo ok e se o DoD pode ser considerado done, e a documentação readme e prompts estao ok, e se os commits estão ok".
- **Prompt 3 (correção + opcionais):** "Vamos executar esse plano e tratar também dos itens opcionais".
- **Resultado/Decisão:**
  - Middleware `core.observability.RegistrarMetricasMiddleware` com latência, normalização de IDs/UUIDs e instrumentação restrita a `/api/` (`/health`, `/admin`, `/static` e docs ficam de fora para não distorcer a amostra).
  - Modelo `RequisicaoMetrica` + migração `0006_requisicaometrica`; retenção por `manage.py limpar_metricas --dias N [--dry-run]`.
  - **Hit rate real de cache:** janela por thread em `core.cache_metrics`, aberta/fechada pelo middleware e gravada em `cache_hits`/`cache_misses`/`cache_bypasses`. Bypass não entra no denominador.
  - Página multipage `dashboard/pages/2_Desempenho_da_API.py` com KPIs, throughput/latência por hora, distribuição **por classe** 2xx/3xx/4xx/5xx (com detalhe por código), requisições por endpoint, filtros de período/endpoint/classe e `@st.cache_data(ttl=60)`.
  - Bloco de pedidos por status rotulado como estado persistido (`core_pedido`), não como profundidade de fila do broker.
  - README (subida, acesso, tráfego, toggle e retenção), `docs/aulas/20-desempenho.md`, `docs/CHANGELOG.md`, `specs/README.md` e `.env.example` atualizados.
- **Revisão humana/ajuste manual:** a primeira versão havia sobrescrito `api/core/models.py` e `api/core/serializers.py` com uma variante antiga do domínio (sem `idempotency_key`, `slug`, `is_active`, estados do pagamento e `CANAL_CHOICES`), o que quebrava `manage.py check` e a coleta da suíte. Ambos foram restaurados do HEAD e a Aula 20 reaplicou somente `RequisicaoMetrica`. Também foram corrigidos o gráfico de status (classes em vez de códigos crus), a hit rate (medida em vez de proxy por latência) e a documentação de retenção.

## [2026-10-28] Aula 21 - Consulta de Dados em Linguagem Natural (Texto-para-SQL)

- **Ferramenta:** opencode (DeepSeek V4.1 Flash Free).
- **Contexto:** Spec `specs/spec_da_aula_21.md` - endpoint `POST /api/v1/ask_sql/` com prompt+DDL do schema, extração limpa do SQL, execução read-only/allow-list `SELECT`, erros claros, página Streamlit com campo de pergunta + SQL + `st.dataframe`, e registro em `PROMPTS.md`/`README.md`.
- **Prompt do usuário:** "Estou estudando programação avançada com IA e hoje estamos na aula 21. Vamos seguir as tarefas e responsabilidades da spec @specs/spec_da_aula_21.md para que os itens do seu DoD sejam concluidos." Em seguida: "vamos implementar o plano".
- **Decisões:** provedor `ProvedorMockSql` determinístico (mesma porta `ProvedorLlm` da Aula 14, sem rede/credenciais), endpoint restrito a `IsAdminRole` e login por formulário no Streamlit com JWT em `st.session_state`. O pipeline prompt→extração→validação→execução é real; só a tradução português→SQL é mock.
- **Template de prompt (system):**

  ```text
  Você traduz perguntas de negócio em UMA consulta SQL de leitura para PostgreSQL.

  Regras obrigatórias:
  1. Responda APENAS com a consulta SQL. Sem explicação, sem markdown, sem cercas
     de código e sem ponto e vírgula final.
  2. Use somente SELECT (inclusive WITH ... SELECT). Nunca INSERT, UPDATE,
     DELETE, DROP, ALTER, CREATE, TRUNCATE, COPY, CALL, SET ou comandos de
     transação.
  3. Use somente as tabelas e colunas do SCHEMA abaixo. Não invente tabelas,
     colunas, endereços ou dados.
  4. Junte tabelas com JOIN explícito e condição ON. Nunca use junção por vírgula.
  5. Nunca use SELECT *; liste as colunas. Em agregações, dê um alias ao
     resultado (ex.: COUNT(*) AS total_pedidos).
  6. "últimos N" significa ORDER BY <data> DESC LIMIT N. "maiores/mais caros"
     significa ORDER BY <valor> DESC. Sempre limite a no máximo 200 linhas.
  7. Não use comentários (-- ou /* */), nem funções de sistema/arquivo
     (pg_sleep, pg_read_file, dblink, set_config).
  8. Datas relevantes: auth_user.date_joined, auth_user.last_login,
     core_pedido.created_at, core_pagamento.created_at,
     core_notificacao.enviada_em. Valores monetários: core_pedido.total,
     core_pagamento.valor, core_item.price.
  9. Se a pergunta não puder ser respondida com este schema, responda exatamente
     NAO_SUPORTADO.

  EXEMPLOS:
  Pergunta: Quais os 3 últimos pedidos?
  SQL: SELECT id, usuario_id, status, total, created_at FROM core_pedido ORDER BY created_at DESC LIMIT 3

  Pergunta: Quantos pedidos existem por status?
  SQL: SELECT status, COUNT(*) AS total_pedidos FROM core_pedido GROUP BY status ORDER BY total_pedidos DESC
  ```

  O system é seguido do contexto DDL/describe gerado por `core/ask_sql/schema.py` (tabelas, tipos, relacionamentos, glossário e tabelas inexistentes) e a pergunta vai como `PERGUNTA: <texto>`.
- **Refinamentos de segurança (além do prompt):**
  - Allow-list de tabelas/colunas (`constantes.py`): `auth_user`, `core_pedido`, `core_pagamento`, `core_notificacao`, `core_item`, `core_category`; fora `core_requisicao_metrica`, `django_*`, `auth_group*` e `auth_permission`.
  - `auth_user.password`, `idempotency_key`, `transacao_id` e `session_key` nunca entram no schema nem podem ser projetadas.
  - `enderecos_entrega` não existe no domínio: o prompt declara a ausência e a resposta vira 422, sem inventar tabela.
  - Validação: começa por `SELECT`/`WITH`, um comando, sem comentários/aspas/`$`, sem DML/DDL, sem `SELECT *`, sem `FOR UPDATE`, sem funções perigosas, `LIMIT` obrigatório e clampado.
  - Execução: `SET TRANSACTION READ ONLY` + `set_config('statement_timeout', ...)` + `fetchmany(max+1)` para detectar truncamento.
- **Resultado/Decisão:** criados `api/core/ask_sql/*`, `api/core/llm/mock_sql.py`, `dashboard/ask_sql.py`, `dashboard/pages/3_Consulta_em_Linguagem_Natural.py` e `docs/aulas/21-consulta-linguagem-natural.md`; atualizados `core/llm/servico.py` (fábrica por tarefa), `core/urls.py`, `api/config/settings.py`, `docker-compose.yml`, `.env.example`, `pyproject.toml`, `docs/openapi.yaml`, `README.md`, `docs/CHANGELOG.md` e `specs/README.md`. Suíte: 398 testes, cobertura 89,64%.
- **Revisão humana/ajuste manual:** o mock devolve `NAO_SUPORTADO` para perguntas fora dos padrões; o campo `question` recusa tipos não textuais (o `CharField` do DRF converte `42` em `"42"`); a transação read-only é provada com `django_db(transaction=True)`; as páginas Streamlit ficaram fora da cobertura porque executam UI no import (a lógica testável está em `dashboard/ask_sql.py`).
