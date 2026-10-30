# SynapseShop

[![CI](https://github.com/Gilgamashed/AulaAI02/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Gilgamashed/AulaAI02/actions/workflows/ci.yml)

Backend de Pedidos com Inteligência Artificial — MVP do projeto da squad.

## Equipe

> Lista provisória — atualizar conforme novos membros entrarem na squad.

| Integrante          | Papel                                            |
| ------------------- | ------------------------------------------------ |
| Caius I O           | Tech Lead / Product Owner / DevOps / SRE / Arquiteto / Desenvolvedor / Especialista em IA |

## Domínio

Loja de departamentos: catálogo de produtos variados, com pedidos gerados e
processados ponta a ponta.

## MVP — Backend de Pedidos com IA

O MVP consiste em um backend capaz de receber pedidos e processar o fluxo
**Pedido → Pagamento → Notificação**, com suporte de inteligência artificial
integrada. Nenhum framework web, banco de dados ou serviço externo é definido
nesta fase inicial; o desenvolvimento segue a metodologia **SpecDD** de forma
iterativa e incremental.

## Arquitetura-alvo (6 camadas)

1. **Clientes/Canais** — pontos de entrada que consomem o backend.
2. **Gateway de API e Autenticação** — DRF + FastAPI, com JWT e *throttling*.
3. **Serviços de Negócio** — `order`, `payment`, `inventory` e `notification`.
4. **Camada de IA** — serviços de inteligência artificial do backend de pedidos.
5. **Infraestrutura de Dados e Mensageria** — PostgreSQL, Redis, RabbitMQ/Kafka.
6. **Observabilidade, Qualidade e Entrega** — Streamlit, pytest, OpenAPI, CI/CD.

### Diagrama (versão inicial)

> Descrição textual provisória (a imagem oficial da arquitetura será adicionada
> quando disponível).

```
Clientes/Canais
      │
      v
Gateway de API + Autenticação (DRF + FastAPI, JWT, throttling)
      │
      v
Serviços de Negócio (order → payment → inventory → notification)
      │
      v
Camada de IA
      │
      v
Infraestrutura de Dados e Mensageria (PostgreSQL, Redis, RabbitMQ/Kafka)
      │
      v
Observabilidade | Qualidade | Entrega (Streamlit, pytest, OpenAPI, CI/CD)
```

## Stack de referência

Docker, Django REST Framework, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Redis.

## Como subir o ambiente

Infraestrutura conteinerizada com Docker Compose (Aula 2/3, estendida até a
Aula 20). São **oito serviços**:

| Serviço      | Imagem             | Função                                               |
| ------------ | ------------------ | ---------------------------------------------------- |
| `api`        | build do Dockerfile | API Django REST Framework: `/health` + rotas CRUD em `/api/v1/` (porta 8000) |
| `db`         | `postgres:16-alpine` | Banco PostgreSQL (volume `pgdata` para persistência); porta interna `db:5432` **publicada em `localhost:5432`** para permitir comandos de gerenciamento locais (venv) |
| `redis`      | `redis:7-alpine`   | Cache-aside do microsserviço de estoque (Aula 8) **e** janela de dedupe dos dois fluxos Kafka (Aulas 9 a 11) |
| `kafka`      | Apache Kafka (KRaft, modo único nó) | Broker de mensageria. Roda com `auto.create.topics.enable=false`: quem cria os tópicos é a aplicação (ver "Subir o ambiente") |
| `inventory`  | build de `services/inventory/Dockerfile` | Microsserviço FastAPI de estoque: `/health`, `/docs` e CRUD em `/api/v1/inventory` (porta 8001); persistência própria no PostgreSQL governada pelo Alembic (Aula 6) |
| `worker-kafka` | mesma imagem da `api` | Consumidor do fluxo de **pedidos** (`pedidos.criados`, grupo `synapseshop-pedidos`) |
| `worker-pagamentos` | mesma imagem da `api` | Consumidor do fluxo de **pagamentos** (`pagamentos.registrados`, grupo `synapseshop-pagamentos`) |
| `dashboard` | build de `dashboard/Dockerfile` | Painel Streamlit: analítico (Aula 19) e de desempenho da API (Aula 20); conexão segura, SQLi mitigado, filtros e cache (porta 8501) |

Existe ainda um serviço `rabbitmq`, mas ele está atrás do profile `rabbitmq`
(Aulas 9/10) e **não sobe** no caminho Kafka — que é o broker padrão da Aula 11.
Para usá-lo: `docker compose --profile rabbitmq up -d`.

O `Dockerfile` usa **multistage build** (`builder` prepara as dependências;
`runtime` copia apenas o necessário) com cache eficiente de dependências e
execução via usuário não-root `appuser`. O serviço `api` só inicia depois que
o banco responde com sucesso ao `healthcheck` (`depends_on` +
`service_healthy`), e é o `api` quem aplica as migrações no startup (ver o
`CMD` do `Dockerfile`) — os dois workers esperam `api: service_healthy` para não
consumir antes das tabelas existirem.

### Pré-requisitos

- Docker Desktop (com WSL2) e Docker Compose.
- Arquivo `.env` na raiz com as credenciais do banco (usar `.env.example`
  como referência). O Compose o carrega automaticamente.

### Subir o ambiente

```bash
docker compose up -d --build
```

Painel Streamlit: [http://localhost:8501](http://localhost:8501). Simulação de SQL Injection:

```bash
docker compose run --rm dashboard python -m dashboard.simular_sqli
```

Não é preciso declarar os tópicos Kafka na mão: o broker sobe com
`auto.create.topics.enable=false`, então quem cria a topologia é a aplicação —
cada worker declara a topologia do **seu** fluxo antes de assinar o tópico
(`kafka_consumidor.py`, em `rodar()`), e o produtor a declara a cada publicação.
É isso que faz `docker compose up` bastar. O comando `declarar_topicos_kafka`
existe para **inspecionar** e para casos de recuperação, não como passo de
instalação.

O passo que **não** é opcional é o seed de usuários:

```bash
docker compose exec api python api/manage.py seed_auth
```

As migrations não criam usuários e o Compose não roda o seed. Sem este comando
**não existe `demo_user`**, e como todo endpoint de escrita exige JWT, o fluxo
pedido ➔ pagamento ➔ notificação fica impossível de exercitar. É idempotente:
pode repetir à vontade. As credenciais estão na seção
[Autenticação JWT](docs/autenticacao.md).

### Validar a disponibilidade

```bash
curl http://localhost:8000/health
# {"status": "ok", "service": "synapseshop-api", "broker": "kafka",
#  "fluxos": {"pedidos": {...}, "pagamentos": {...}}}

curl http://localhost:8001/health
# {"status": "ok", "service": "synapseshop-inventory"}
```

`fluxos` traz a **topologia** de cada fluxo (tópico, grupo, partições, retenção,
tópico de DLQ, escada de reentrega). Ele não traz `lag` nem contagem de DLQ de
propósito: o Compose usa `/health` como `healthcheck` do container, e ler os
watermarks a cada sondagem transformaria o endpoint de liveness em carga no
broker. Para o estado que se move:

```bash
docker compose exec api python api/manage.py declarar_topicos_kafka --fluxo pagamentos --json
docker compose exec api python api/manage.py inspecionar_dlq_kafka --fluxo pagamentos
```

### Acompanhar os logs

```bash
docker compose logs -f api          # logs do serviço API
docker compose logs -f db           # logs do PostgreSQL (ex.: "database system is ready")
docker compose logs -f inventory    # logs do microsserviço de estoque
docker compose logs -f worker-kafka       # consumo do fluxo de pedidos
docker compose logs -f worker-pagamentos  # consumo do fluxo de pagamentos
```

Os dois workers emitem **JSON**, e o campo `fluxo` distingue um do outro — o
mesmo `grep` serve para os dois:

```bash
docker compose logs worker-pagamentos | grep '"fluxo": "pagamentos"'
```

### Derrubar o ambiente

```bash
docker compose down             # encerra os containers (mantém o volume pgdata)
docker compose down -v          # encerra e apaga o volume (atenção: apaga os dados)
```

## Rotas da API (Aula 4)

A API principal usa **Django REST Framework** e expõe o CRUD de produtos
eletrônicos sob o prefixo versionado `/api/v1/`. As migrações são aplicadas
automaticamente no startup (o banco já está saudável via `depends_on`).

| Rota                           | Verbos                    | Descrição                                   |
| ------------------------------ | ------------------------- | ------------------------------------------- |
| `/health`                      | GET                       | Healthcheck da API (200)                    |
| `/api/v1/`                     | GET                       | Root do router (lista as rotas disponíveis) |
| `/api/v1/categories/`          | GET, POST                 | Listar / criar categorias                   |
| `/api/v1/categories/{id}/`     | GET, PUT, PATCH, DELETE   | Detalhe / atualizar / excluir categoria     |
| `/api/v1/items/`               | GET, POST                 | Listar / criar produtos eletrônicos         |
| `/api/v1/items/{id}/`          | GET, PUT, PATCH, DELETE   | Detalhe / atualizar / excluir produto       |
| `/api/v1/ask_sql/`             | POST (admin)              | Pergunta em português → SELECT validado     |

Status codes: **200** OK, **201** Created, **204** No Content, **400** Bad
Request, **404** Not Found. Validações customizadas: preço não-negativo, SKU no
formato `XXXX-AAAA-BBBB`, nomes de categoria/produto/marca/modelo não-vazios
(sem espaços em branco), `specifications` como objeto JSON e unicidade de
SKU/categoria.

> **Desde a Aula 7** essas rotas ganharam a camada de acesso: o **GET** (list/
> detail) permanece público e agora é paginado e filtrável; as escritas exigem
> **JWT** — **POST** aceita os papéis `user`/`admin`, enquanto **PUT/PATCH/
> DELETE** são restritos ao papel `admin`. Detalhes em
> [Autenticação JWT, papéis e throttling (Aula 7)](docs/autenticacao.md).


Coleção exportada para teste (importar no Postman e definir a variável
`base_url` como `http://localhost:8000`):
`collections/synapseshop_aula4.postman_collection.json`. Exemplos `curl` em
[docs/aulas/04-api.md](docs/aulas/04-api.md).

## Registro das aulas

O detalhamento técnico de cada aula foi movido para `docs/`; este README
mantém o estado atual do projeto e o índice para navegação.

| Aula | Tópico | Documento |
| ---- | ------ | --------- |
| 4 | CRUD da API com Django REST Framework | [docs/aulas/04-api.md](docs/aulas/04-api.md) |
| 5 | Microsserviço de estoque com FastAPI | [docs/aulas/05-inventory.md](docs/aulas/05-inventory.md) |
| 6 | Modelagem relacional, índices e migrações | [docs/aulas/06-modelagem.md](docs/aulas/06-modelagem.md) |
| 7 | Autenticação JWT, papéis e throttling | [docs/autenticacao.md](docs/autenticacao.md) |
| 8 | Cache-aside com Redis | [docs/aulas/08-cache.md](docs/aulas/08-cache.md) |
| 9 | Mensageria assíncrona (RabbitMQ) | [docs/aulas/09-mensageria.md](docs/aulas/09-mensageria.md) |
| 10 | Apache Kafka: partições, offsets e DLQ | [docs/aulas/10-kafka.md](docs/aulas/10-kafka.md) |
| 11 | Pagamento, notificação e segundo fluxo Kafka | [docs/aulas/11-pagamentos.md](docs/aulas/11-pagamentos.md) |
| 12 | Testes automatizados e cobertura | [docs/testes.md](docs/testes.md) |
| 13 | Checklist do Integrador Externo | [docs/integrador.md](docs/integrador.md) |
| 14 | Assistente de IA e llm_service | [docs/aulas/14-ia.md](docs/aulas/14-ia.md) |
| 19 | Conexão segura, SQL Injection e painel Streamlit | [docs/aulas/19-dashboard.md](docs/aulas/19-dashboard.md) |
| 20 | Dashboard de desempenho da API | [docs/aulas/20-desempenho.md](docs/aulas/20-desempenho.md) |
| 21 | Consulta em linguagem natural (texto-para-SQL) | [docs/aulas/21-consulta-linguagem-natural.md](docs/aulas/21-consulta-linguagem-natural.md) |
| 22 | Pipeline de CI/CD com GitHub Actions | [docs/aulas/22-ci-cd.md](docs/aulas/22-ci-cd.md) |

## Documentação útil

- [Autenticação: tutorial operacional](docs/autenticacao.md) (login, usuários, admin)
- [Contrato OpenAPI](docs/openapi.yaml) — Swagger UI em `/docs/`, ReDoc em `/redoc/`
- [Contratos de evento](docs/contracts/)
- [Specs por aula (SpecDD)](specs/README.md)
- [Visão geral do curso](docs/curso/visao-geral.md)
- [PROMPTS.md](PROMPTS.md) — histórico de uso de IA (entrega obrigatória)

## Conexão Segura, SQL Injection e Painel Streamlit (Aula 19)

### Variáveis de ambiente
Configurar no `.env`:

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

### Segurança da conexão
- **SSL/TLS obrigatório:** `DB_SSLMODE=require` com certificado TLS no PostgreSQL.
- **Pooling:** configurado via SQLAlchemy (`pool_size`, `max_overflow`, `pool_timeout`, `pool_recycle`), `pool_pre_ping` habilitado.
- **Timeouts:** `connect_timeout` e `statement_timeout` aplicados.
- **Credenciais via ambiente:** nunca hardcoded.

### Prevenção a SQL Injection (Zero Interpolação)
- **Obrigatório:** usar *bind parameters* (SQLAlchemy Core/`text` com parâmetros). Vedada interpolação direta de strings em SQL.
- **Ordenação dinâmica segura:** *allow-list* (`dashboard/security.py`) para `ORDER BY`.
- **Filtros robustos:** cláusulas parametrizadas com filtros por data/status/ID.
- **Módulos:** `dashboard/db.py`, `dashboard/queries.py`, `dashboard/security.py`, `dashboard/simular_sqli.py`. Simulação: `python -m dashboard.simular_sqli`.

### Painel Streamlit
- **Serviço:** `dashboard` (porta `8501`), com *bind-mount* para *live reload* (`runOnSave=true`).
- **Funcionalidades:** filtros dinâmicos (data, status, ID), ordenação segura, tabela (`st.dataframe`), gráfico (`st.bar_chart`), métricas.
- **Cache:** `@st.cache_data(ttl=60)`.
- **Documentação:** [docs/aulas/19-dashboard.md](docs/aulas/19-dashboard.md).

## Dashboard de Desempenho da API (Aula 20)

O dashboard multipage do Streamlit inclui a página **Desempenho da API**
(menu lateral em `http://localhost:8501`). A instrumentação é feita pelo
middleware `core.observability.RegistrarMetricasMiddleware`, que grava uma
linha em `core_requisicao_metrica` por requisição atendida sob `/api/`.
`/health`, `/admin`, `/static` e docs ficam de fora para não distorcer a
amostra.

### Funcionalidades

- **KPIs:** total de requisições, latência média (ms), p95 (ms), erros
  (4xx/5xx), taxa de erro (%) e *cache hit rate* real.
- **Gráficos:** throughput por hora, latência ao longo do tempo
  (média/p95), distribuição por classe de status (2xx/3xx/4xx/5xx) e
  requisições por endpoint.
- **Filtros interativos:** período (data inicial/final), endpoint e classe
  de status. Sem seleção em um filtro, ele não restringe o resultado.
- **Cache:** o middleware grava os *deltas* de hits/misses/bypasses da
  própria requisição (via `core.cache_metrics`), então a hit rate exibida é
  medida, não estimada pela latência.
- **Pedidos por status:** foto do estado em `core_pedido`. Não é
  profundidade de fila do broker — o Kafka/RabbitMQ não é consultado por
  HTTP.
- **Carregamento:** `@st.cache_data(ttl=60)` nas consultas do painel.

### Como subir e acessar

A migração `0006` é aplicada pelo próprio serviço `api` no startup:

```bash
docker compose up -d --build
```

Também é possível reconstruir só o que mudou:

```bash
docker compose up -d --build api dashboard
```

Acesse [http://localhost:8501](http://localhost:8501) → **Desempenho da API**
e gere tráfego para popular as métricas:

```bash
# Bash
for i in $(seq 1 10); do curl -s http://localhost:8000/api/v1/items/ > /dev/null; done
```

```powershell
# PowerShell
1..10 | ForEach-Object {
    Invoke-RestMethod -Uri "http://localhost:8000/api/v1/items/" -ErrorAction SilentlyContinue | Out-Null
}
```

### Configuração e retenção

- `API_METRICS_ENABLED=false` desliga a instrumentação (padrão: `true`).
- O log cresce a cada requisição; pode ser podado com:

  ```bash
  docker compose exec api python api/manage.py limpar_metricas --dias 30
  ```

  Use `--dry-run` para apenas contar as linhas que seriam removidas.
- Os contadores de cache são por processo do gunicorn (1 worker no Compose).
  Com múltiplos workers, cada processo conta a sua parte e o dashboard soma
  as linhas gravadas.

Documentação técnica: [docs/aulas/20-desempenho.md](docs/aulas/20-desempenho.md).

## Consulta em Linguagem Natural / Texto-para-SQL (Aula 21)

O endpoint `POST /api/v1/ask_sql/` recebe uma pergunta de negócio em português,
monta o prompt com o **schema permitido**, gera uma consulta SQL **somente
leitura**, valida, executa com timeout e devolve o SQL e as linhas em JSON.
A página **Consulta em Linguagem Natural** do Streamlit consome esse endpoint.

O acesso é restrito ao papel **admin** (`IsAdminRole`): a consulta pode ler
pedidos, pagamentos e usuários de toda a base. O login do painel usa
`/api/v1/auth/token/` e guarda o JWT na sessão do Streamlit.

### Exemplo (PowerShell)

```powershell
$login = Invoke-RestMethod -Method Post `
  -Uri 'http://localhost:8000/api/v1/auth/token/' `
  -ContentType 'application/json' `
  -Body (@{ username='demo_admin'; password='demo-admin@Synapse2026' } | ConvertTo-Json -Compress)

$headers = @{ Authorization = "Bearer $($login.access)" }
$corpo = @{ question = 'Quais os 5 últimos usuários cadastrados?' } | ConvertTo-Json -Compress

Invoke-RestMethod -Method Post `
  -Uri 'http://localhost:8000/api/v1/ask_sql/' `
  -Headers $headers -ContentType 'application/json' -Body $corpo |
  ConvertTo-Json -Depth 6
```

```bash
# Bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo_admin","password":"demo-admin@Synapse2026"}' |
  python -c 'import json,sys; print(json.load(sys.stdin)["access"])')

curl -s -X POST http://localhost:8000/api/v1/ask_sql/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Qual a soma do valor dos últimos 3 pedidos?"}'
```

Resposta (200):

```json
{
  "question": "Qual a soma do valor dos últimos 3 pedidos?",
  "sql": "SELECT SUM(total) AS soma_total FROM (SELECT total FROM core_pedido ORDER BY created_at DESC LIMIT 3) AS ultimos_pedidos",
  "columns": ["soma_total"],
  "rows": [{"soma_total": 60.0}],
  "row_count": 1,
  "truncated": false,
  "meta": {"tokens_prompt": 812, "tokens_output": 32, "modelo": "mock-sql"}
}
```

Erros: **400** payload inválido · **401** sem JWT · **403** sem papel admin ·
**422** pergunta fora do domínio, SQL proibido ou erro de execução (inclui
`examples`) · **500** IA mal configurada · **502** resposta inválida do
provedor · **503** provedor/banco indisponível.

### Interface Streamlit

1. Suba o ambiente e rode o seed:

   ```bash
   docker compose up -d --build
   docker compose exec api python api/manage.py seed_auth
   ```

2. Acesse [http://localhost:8501](http://localhost:8501) → **Consulta em
   Linguagem Natural**.
3. Entre com `demo_admin` / `demo-admin@Synapse2026`, digite a pergunta (ou
   escolha um exemplo) e clique em **Consultar**.
4. A página mostra o SQL gerado (`st.code`), a contagem/truncamento e a tabela
   (`st.dataframe`).

### Segurança em camadas

- **Validação:** apenas `SELECT`/`WITH`, um único comando, sem comentários,
  allow-list das tabelas `auth_user`, `core_pedido`, `core_pagamento`,
  `core_notificacao`, `core_item` e `core_category`; bloqueio de `SELECT *`,
  colunas sensíveis (`password`, `idempotency_key`, `transacao_id`),
  `FOR UPDATE`, `pg_catalog`/`information_schema` e funções perigosas
  (`pg_sleep`, `nextval`, `dblink` etc.).
- **Execução:** transação `READ ONLY`, `statement_timeout` local
  (`ASK_SQL_TIMEOUT_MS`) e `LIMIT` obrigatório/clampado
  (`ASK_SQL_MAX_LINHAS`).
- **Defesa em profundidade:** mesmo que o provedor desobedeça ao prompt, o
  banco recusa escrita na transação read-only.

### Limitações registradas

- O provedor desta aula é o **mock determinístico** `ProvedorMockSql` (mesma
  porta `ProvedorLlm` da Aula 14), sem rede e sem credenciais. Ele cobre os
  padrões de negócio documentados; não é linguagem natural irrestrita. Um
  adaptador de LLM real entra pela mesma porta sem mudar validação/execução.
- `enderecos_entrega` **não existe** neste domínio; perguntas sobre endereço
  retornam 422 em vez de inventar tabela/colunas.
- A transação read-only e o `statement_timeout` protegem contra mutação e
  consultas caras; não substituem um papel de banco exclusivamente read-only
  (evolução futura).

### Configuração

```env
LLM_MODEL_SQL=mock-sql
ASK_SQL_MAX_LINHAS=200
ASK_SQL_TIMEOUT_MS=3000
ASK_SQL_MAX_TOKENS=500
ASK_SQL_LOG_LEVEL=INFO
DASHBOARD_API_URL=http://api:8000
```

Documentação técnica e roteiro de teste:
[docs/aulas/21-consulta-linguagem-natural.md](docs/aulas/21-consulta-linguagem-natural.md).

## Pipeline de CI/CD com GitHub Actions (Aula 22)

O workflow [`.github/workflows/ci.yml`](.github/workflows/ci.yml) roda a cada
push em `main`, `master` e `dev`, em pull requests para o branch principal e
também sob demanda (`workflow_dispatch`).

| Job | Runner | O que valida |
| --- | --- | --- |
| `test-and-lint` | `ubuntu-latest` | `ruff check .`, suíte `pytest` completa e gate de cobertura de 85% |
| `docker-build` | `ubuntu-latest` | `docker build -t synapseshop-api:test .` (Dockerfile multistage) |

A suíte não usa Redis, Kafka nem RabbitMQ: `config.settings_test` troca os
caches por `LocMemCache` e o `tests/conftest.py` substitui a publicação de
eventos por um duplo em memória. O único serviço externo é um PostgreSQL 16
efêmero, porque o `pytest-django` cria e destrói o banco `test_*`.

### Variáveis e segredos

Nenhum segredo é obrigatório: o banco do runner é descartável e
`config.settings_test` fixa `SECRET_KEY` e `JWT_SIGNING_KEY`. O workflow lê
`secrets.DJANGO_SECRET_KEY` quando ele existe e cai num valor efêmero de CI
quando não existe — assim um fork ou um PR sem acesso a secrets também roda.

Para cadastrar o segredo (opcional):

```bash
gh secret set DJANGO_SECRET_KEY --repo Gilgamashed/AulaAI02
```

Ou em **Settings → Secrets and variables → Actions → New repository secret**.
O mesmo painel serve para variáveis não sensíveis (`vars.*`), que não são
necessárias nesta aula.

### Rodar o equivalente local

```bash
docker compose build tests            # instala as dependências de dev (inclui ruff)
docker compose run --rm tests         # pytest + cobertura (gate de 85%)
docker compose run --rm tests python -m ruff check .
docker build -t synapseshop-api:test .
```

O job publica `reports/junit.xml`, `reports/coverage.xml` e `htmlcov/` como
artefatos (`relatorios-testes`, retenção de 7 dias), mesmo quando a suíte
falha.

### Limites desta aula

Deploy contínuo, publicação de imagem em registry (DockerHub/GHCR) e cache
avançado de dependências ficam para a Aula 23. O job `docker-build` apenas
prova que a imagem constrói localmente no runner.

Documentação técnica: [docs/aulas/22-ci-cd.md](docs/aulas/22-ci-cd.md).

## Referências

- [Histórico de uso de IA generativa](PROMPTS.md)
- [Histórico de alterações](docs/CHANGELOG.md)
- [Diretriz SpecDD](specs/00_diretriz_incremental_specdd.md)
