# SynapseShop

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
Aula 11). São **sete serviços**:

| Serviço      | Imagem             | Função                                               |
| ------------ | ------------------ | ---------------------------------------------------- |
| `api`        | build do Dockerfile | API Django REST Framework: `/health` + rotas CRUD em `/api/v1/` (porta 8000) |
| `db`         | `postgres:16-alpine` | Banco PostgreSQL (volume `pgdata` para persistência); porta interna `db:5432` **publicada em `localhost:5432`** para permitir comandos de gerenciamento locais (venv) |
| `redis`      | `redis:7-alpine`   | Cache-aside do microsserviço de estoque (Aula 8) **e** janela de dedupe dos dois fluxos Kafka (Aulas 9 a 11) |
| `kafka`      | Apache Kafka (KRaft, modo único nó) | Broker de mensageria. Roda com `auto.create.topics.enable=false`: quem cria os tópicos é a aplicação (ver "Subir o ambiente") |
| `inventory`  | build de `services/inventory/Dockerfile` | Microsserviço FastAPI de estoque: `/health`, `/docs` e CRUD em `/api/v1/inventory` (porta 8001); persistência própria no PostgreSQL governada pelo Alembic (Aula 6) |
| `worker-kafka` | mesma imagem da `api` | Consumidor do fluxo de **pedidos** (`pedidos.criados`, grupo `synapseshop-pedidos`) |
| `worker-pagamentos` | mesma imagem da `api` | Consumidor do fluxo de **pagamentos** (`pagamentos.registrados`, grupo `synapseshop-pagamentos`) |

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
[Autenticação JWT](#autenticação-jwt-papéis-e-throttling-aula-7).

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

Status codes: **200** OK, **201** Created, **204** No Content, **400** Bad
Request, **404** Not Found. Validações customizadas: preço não-negativo, SKU no
formato `XXXX-AAAA-BBBB`, nomes de categoria/produto/marca/modelo não-vazios
(sem espaços em branco), `specifications` como objeto JSON e unicidade de
SKU/categoria.

> **Desde a Aula 7** essas rotas ganharam a camada de acesso: o **GET** (list/
> detail) permanece público e agora é paginado e filtrável; as escritas exigem
> **JWT** — **POST** aceita os papéis `user`/`admin`, enquanto **PUT/PATCH/
> DELETE** são restritos ao papel `admin`. Detalhes em
> [Autenticação JWT, papéis e throttling (Aula 7)](#autenticação-jwt-papéis-e-throttling-aula-7).

### Exemplos

```bash
curl -X POST http://localhost:8000/api/v1/categories/ \
  -H "Content-Type: application/json" \
  -d '{"name": "Smartphones", "description": "Dispositivos móveis"}'

curl -X POST http://localhost:8000/api/v1/items/ \
  -H "Content-Type: application/json" \
  -d '{"name": "iPhone 15 128GB", "brand": "Apple", "model": "A3090",
       "sku": "APL-IP15-128", "price": 5499.90, "category": 1}'
```

Coleção exportada para teste (importar no Postman e definir a variável
`base_url` como `http://localhost:8000`):
`collections/synapseshop_aula4.postman_collection.json`.

## Microsserviço de estoque (Aula 5)

Microsserviço complementar de inventário em **FastAPI** (`services/inventory/`),
na porta **8001** (a 8000 é do Django). O domínio é o estoque real:
`sku`, `name`, `quantity` (disponível), `reserved` e `reorder_level`. Na Aula 5
a persistência era em memória; a partir da Aula 6 o estoque é persistido em
PostgreSQL com esquema governado pelo Alembic (ver seção da Aula 6).

| Rota                            | Verbos                  | Descrição                                      |
| ------------------------------- | ----------------------- | ---------------------------------------------- |
| `/`                             | GET                     | Metadados do serviço (name/version)            |
| `/health`                       | GET                     | Healthcheck do serviço (200)                   |
| `/docs`                          | GET                     | Swagger UI (OpenAPI)                           |
| `/api/v1/inventory`             | GET, POST               | Listar / registrar item de estoque             |
| `/api/v1/inventory/{sku}`       | GET, PATCH, DELETE      | Detalhe / atualizar parcial / excluir item     |

Respostas no envelope padrão `{status, data, message}`. Status codes: **200**
OK, **201** Created, **204** No Content, **400** Bad Request (payload ou path
inválido — handler customizado, o padrão do FastAPI seria 422), **404** Not
Found, **409** Conflict (SKU duplicado). O SKU segue o padrão `^[A-Z]{2,4}-[A-Z0-9-]+$`
da Aula 4; `quantity`/`reserved`/`reorder_level` são `>= 0`; PATCH exige ao
menos um campo.

### Exemplo

```bash
curl -X POST http://localhost:8001/api/v1/inventory \
  -H "Content-Type: application/json" \
  -d '{"sku": "APL-IP15-128", "name": "iPhone 15 128GB",
       "quantity": 10, "reserved": 0, "reorder_level": 5}'
```

Qualidade do serviço validada com `ruff` e `mypy` (config em
`services/inventory/pyproject.toml`).

Coleção exportada para teste (importar no Postman e definir a variável
`base_url` como `http://localhost:8001`):
`collections/synapseshop_aula5.postman_collection.json`.

## Modelagem relacional, índices e migrações (Aula 6)

### Decisão arquitetural: dois ORMs no mesmo PostgreSQL

O banco `synapse` é compartilhado entre a API principal e o microsserviço de
estoque, mas cada camada é **dona** das próprias tabelas — o que evita qualquer
conflito de versionamento de schema:

| Dono    | Tabelas                                                  | Versionamento                          |
| ------- | -------------------------------------------------------- | -------------------------------------- |
| Django  | `auth_*`, `core_*`, `django_session`, `django_migrations` | `python api/manage.py migrate` (Aula 4) |
| FastAPI | `inventory_items` + `alembic_version`                    | `alembic upgrade head` (Aula 6)         |

O `alembic/env.py` filtra o `autogenerate`/`check` via `include_object` para
enxergar **apenas** o metadata do inventory — o Alembic nunca gera DDL para as
tabelas do Django, mesmo estando no mesmo banco.

### Modelagem relacional (entidade User)

A entidade **User** foi modelada sobre o sistema de autenticação padrão do
Django (`django.contrib.auth`) — decisão deliberada: reutilizar o `auth_user`
testado/battle-tested em vez de duplicar usuários no SQLAlchemy. O `username`
tem índice **único** (PK + integridade), senha armazenada como hash, e as
relações N:N com `auth_group`/`auth_permission` via tabelas de associação
(`auth_user_groups`, `auth_user_user_permissions`). Decisão: **não** customizar
`AUTH_USER_MODEL` nesta aula (evita antecipar as regras de autenticação/Aula 7).

### Modelagem relacional (entidade InventoryItem — FastAPI)

Tabela `inventory_items` (`services/inventory/app/models.py`, SQLAlchemy 2.0):

| Coluna          | Tipo            | Regra                                              |
| --------------- | --------------- | -------------------------------------------------- |
| `id`            | `BIGINT`        | PK autoincrement                                   |
| `sku`           | `VARCHAR(100)`  | NOT NULL, **UNIQUE** (índice `ix_inventory_items_sku`) |
| `name`          | `VARCHAR(200)`  | NOT NULL                                           |
| `quantity`      | `INTEGER`       | NOT NULL, DEFAULT 0, CHECK `>= 0`                  |
| `reserved`      | `INTEGER`       | NOT NULL, DEFAULT 0, CHECK `>= 0`                  |
| `reorder_level` | `INTEGER`       | NOT NULL, DEFAULT 0, CHECK `>= 0`                  |
| `created_at`    | `TIMESTAMPTZ`   | NOT NULL, `default now()`                          |
| `updated_at`    | `TIMESTAMPTZ`   | NOT NULL, `default now()`, `onupdate now()`        |

**Índices essenciais:** PK (`id`) + índice **único** em `sku` — única chave de
consulta das rotas (get/patch/delete por SKU); o `UNIQUE INDEX` simultaneamente
garante unicidade (integridade) e performance dos lookups.

**Regras de integridade relacional:** PK, NOT NULL, UNIQUE em SKU e CHECKs de
quantidades não-negativas (espelham no banco o `ge=0` do Pydantic). Decisão de
escopo: o `CHECK reserved <= quantity` foi avaliado e **descartado** nesta
etapa — exigiria regra de negócio no PATCH que fugiria do escopo e quebraria o
contrato da Aula 5.

### Índices essenciais por modelo (Django + FastAPI)

Auditoria de índices para **todos os modelos de domínio** do projeto (User,
Item, Category, InventoryItem), derivada das consultas reais (viewsets,
serializers e Admin) e do estado verificado no banco via `pg_indexes`:

| Modelo          | Índice                                        | Propósito                                            | Situação      |
| --------------- | --------------------------------------------- | ---------------------------------------------------- | ------------- |
| User (`auth_user`) | PK `id` + **UNIQUE `username`**           | PK; login/lookups por username (Aula 7)              | nativo Django |
| User            | **`auth_user_email_idx`** (btree em `email`)  | colunas de acesso comuns do modelo User              | **nova** (Aula 6) |
| Item (`core_item`) | PK `id` + **UNIQUE `sku`**                 | PK; identidade/lookups por SKU                       | Aula 4        |
| Item            | `core_item_created_at_desc_idx` (`created_at DESC`) | `ORDER BY -created_at` do ItemViewSet e Admin | **nova** (Aula 6) |
| Item            | `core_item_category_id` (FK)                   | join `Count("items")` do CategoryViewSet            | Aula 4        |
| Category (`core_category`) | PK `id` + **UNIQUE `name`** + **UNIQUE `slug`** | PK; lookups/ordenação por nome; acesso por slug | Aula 4        |
| InventoryItem (`inventory_items`) | PK `id` + **UNIQUE `sku`** | PK; get/patch/delete por SKU | Aula 6 (Alembic) |

As duas novas migrações **Django** garantem a governança de tabelas:

- `core/0002_alter_item_created_at_desc_index` — `AddIndex` do `-created_at`
  (`Meta.indexes` do `Item`). Sem backing index, a listagem padrão da API
  (`ItemViewSet.order_by("-created_at")`) e do Admin faria `seq-scan + sort`.
- `core/0003_auth_user_email_index` — data migration com `RunSQL`
  (`CREATE INDEX IF NOT EXISTS ... ON auth_user (email)`) e `reverse_sql` de
  rollback. O `django.contrib.auth` não indexa `email`; como o app é de
  terceiros, o índice nasce no app `core` — o `auth_user` continua inteiramente
  sob o comando do Django.

O Alembic não precisou de mudanças (a cobertura do `inventory_items` já era
completa) e o `alembic check` segue retornando "No new upgrade operations
detected" — revalidando o filtro `include_object`.

**Deliberadamente fora do escopo de "essencial"** (documentado para não voltar à
pauta sem motivo): busca textual com `ILIKE '%...'` no Admin (exigiria
`pg_trgm` + GIN), índice em `is_active` (baixa cardinalidade, usado só em
`list_filter`) e índice composto `(category_id, created_at DESC)` (padrão
"categoria → mais recentes" ainda não é consultado por nenhuma rota).

### Camadas Repository + Service (transações)

- `app/repositories/inventory.py` — `InventoryRepository`: acesso a dados
  (create/get_by_sku/list/update/delete) sobre uma `Session`.
- `app/services/inventory.py` — `InventoryService`: regras de negócio e
  **fronteira transacional** (commit ao final; rollback em falha), preservando a
  matriz de status da Aula 5 (200/201/204/400/404/409).
- Rotas injetam o serviço via `Depends(get_inventory_service)` (uma sessão por
  requisição em `dependencies.py`).

### Migrações e versionamento (Alembic)

Configuração em `services/inventory/alembic.ini` + `alembic/env.py`. A revisão
inicial `a7f9e2c1b4d8_inventory_items.py` foi criada e aplicada; o startup do
container já executa `alembic upgrade head` antes do uvicorn.

Comandos (via `docker compose`, o banco é o mesmo `db` do Django):

```bash
docker compose exec inventory alembic current   # versão aplicada
docker compose exec inventory alembic history   # histórico de revisões
docker compose exec inventory alembic upgrade head   # aplica pendências
docker compose exec inventory alembic downgrade -1    # rollback seguro
docker compose exec inventory alembic check      # schema em dia com os models
```

**Rollback seguro validado (Alembic):** após o `downgrade -1`, a tabela
`inventory_items` foi removida e as tabelas do Django (`auth_*`, `core_*`,
`django_migrations`) permaneceram intactas; o `upgrade head` restaurou a tabela
e o índice único de SKU. `alembic check` retornou "No new upgrade operations
detected" — schema ↔ models em dia e filtro anti-conflito operando.

**Rollback seguro validado (Django):** as migrações `core` também foram
demonstradas no sentido inverso com o mesmo banco:

```bash
docker compose exec api python api/manage.py migrate core 0001   # desfaz 0003 e 0002
docker compose exec api python api/manage.py migrate core        # reaplica até o head
```

Checkpoints verificados durante a demonstração (via `pg_indexes`/`information_schema`):

| Etapa                                     | `core_item_created_at_desc_idx` | `auth_user_email_idx` | `core_item` (dados/colunas) | `alembic_version` |
| ----------------------------------------- | ----------------------------- | --------------------- | ------------------------- | ----------------- |
| após `downgrade -1` (Alembic)             | presente                      | presente              | 1 linha / 13 colunas        | vazio             |
| após `upgrade head` (Alembic)             | presente                      | presente              | 1 linha / 13 colunas        | `a7f9e2c1b4d8`    |
| após `migrate core 0001` (Django)         | **removido**                  | **removido**          | 1 linha / 13 colunas        | `a7f9e2c1b4d8`    |
| após `migrate core` (Django, head)        | restaurado                    | restaurado            | 1 linha / 13 colunas        | `a7f9e2c1b4d8`    |

Enquanto um sistema revertia, **o estado do outro permaneceu intocado** — prova
do isolamento dos dois versionamentos no mesmo PostgreSQL. Ao final, ambos
convergem: `alembic check` = "No new upgrade operations detected", `migrate --plan`
= "No planned migration operations" e `makemigrations --check` = "No changes
detected".

### Comandos locais de gerenciamento (venv) do Django

A porta `5432` do serviço `db` é publicada em `localhost:5432`, então os
comandos de gerenciamento do Django podem rodar no `.venv` local (além do modo
conteinerizado). Duas observações importantes:

1. **O `makemigrations`/`migrate` consultam a tabela `django_migrations`** — sem
   banco acessível eles travavam na conexão (era esse o timeout). No container a
   `DATABASE_URL` usa o host interno `db`; localmente ela precisa apontar para
   `localhost` com as credenciais do `.env` (não as do default `settings.py`).
2. Comando padrão no PowerShell (monta a `DATABASE_URL` a partir do `.env`):

```powershell
$e = @{}; Get-Content .env | Where-Object { $_ -match '^\w+=' } | ForEach-Object { $k,$v = $_ -split '=',2; $e[$k]=$v }
$env:DATABASE_URL = "postgresql://$($e.POSTGRES_USER):$($e.POSTGRES_PASSWORD)@localhost:5432/$($e.POSTGRES_DB)"
.venv\Scripts\python.exe api\manage.py makemigrations --check     # sem gerar arquivos
.venv\Scripts\python.exe api\manage.py makemigrations core        # gera migração no host
.venv\Scripts\python.exe api\manage.py migrate --plan             # pré-visualiza
.venv\Scripts\python.exe api\manage.py migrate --noinput          # aplica
```

Validado: `makemigrations --check --dry-run` = "No changes detected",
`migrate --noinput` = "No migrations to apply" — sem travamento. Nos
containers, nada muda: `api`/`inventory` continuam usando `db:5432` na rede do
compose.

### Testes transacionais e tempos de execução

Script `services/inventory/scripts/measure_transactions.py` (não usa pytest —
suíte fica para a Aula 12, conforme SpecDD):

```bash
docker compose run --rm inventory python scripts/measure_transactions.py
```

Medições coletadas (50 itens, 1 commit por operação, via `Service`→`Repository`):

| Operação                      | Total     | Média    |
| ----------------------------- | --------- | -------- |
| `create_item` (1 commit/op)   | ~351–660 ms | ~7–13 ms |
| `get_item` por SKU (lookup)   | ~47–113 ms  | ~0,9–2,3 ms |
| `list_items` (50 itens)       | ~3,4 ms     | —        |
| `update_item` (PATCH parcial) | ~275–780 ms | ~5,5–16 ms |
| `delete_item`                 | ~281–750 ms | ~5,6–15 ms |

O script também **demonstra o rollback** de transação (linha inserida em
transação abortada NÃO é persistida) e inspeciona o schema confirmando a
coexistência `auth_*`/`core_*` (Django) + `inventory_items`/`alembic_version`.


## Autenticação JWT, papéis e throttling (Aula 7)

Adiciona a camada de acesso seguro à API do Django. **Decisão:** reutilizar o
`django.contrib.auth` (User/Groups já existentes) sem customizar
`AUTH_USER_MODEL` (alinhado à Aula 6); o JWT entra via
`djangorestframework-simplejwt` e os filtros via `django-filter`.

### Papéis (roles) e usuários demo

Os papéis **admin** e **user** são `Group`s do Django. O comando `seed_auth`
cria os grupos e dois usuários demo (idempotente; senhas sobrescritas apenas
no primeiro import):

```bash
docker compose exec api python api/manage.py seed_auth
```

| Usuário      | Papel  | Senha (DEV)           | Observação                      |
| ------------ | ------ | --------------------- | ------------------------------- |
| `demo_admin` | admin  | `demo-admin@Synapse2026` | `staff` (acessa o Django Admin) |
| `demo_user`  | user   | `demo-user@Synapse2026` | acesso comum à API             |

> Senhas podem ser definidas via `.env` (`SEED_ADMIN_PASSWORD`,
> `SEED_USER_PASSWORD`). As credenciais acima são **somente** para ambiente de
> desenvolvimento.

### Rotas de autenticação (JWT)

| Rota                                | Método | Descrição                                  | Throttle  |
| ----------------------------------- | ------ | ------------------------------------------ | --------- |
| `/api/v1/auth/token/`               | POST   | Login → `{access, refresh}`                | `login` (5/min) |
| `/api/v1/auth/token/refresh/`       | POST   | Troca `refresh` por novo `access`          | `login` (5/min) |
| `/api/v1/auth/token/verify/`        | POST   | Valida um access token                     | —         |

Tokens: `access` expira em **5 min**, `refresh` em **1 dia** (SimpleJWT). A
assinatura usa `JWT_SIGNING_KEY` (ou o `DJANGO_SECRET_KEY` como fallback).

### Matriz de permissões

| Verbo          | Público | user        | admin |
| -------------- | ------- | ----------- | ----- |
| GET list/detail (`/categories/`, `/items/`) | ✅ 200 | ✅ 200 | ✅ 200 |
| POST           | ❌ 401  | ✅ 201      | ✅ 201 |
| PUT/PATCH/DELETE | ❌ 401 | ❌ 403      | ✅ 200/204 |

Implementada com `get_permissions()` em cada viewset; a permissão
`IsAdminRole` (`api/core/permissions.py`) testa o grupo `admin`/superuser.
Anônimo escrevendo → **401**; user em rota administrativa → **403**.

### Throttling e segurança mínima

| Taxa      | Aplica-se a                            |
| --------- | -------------------------------------- |
| `anon` 20/min | requisições não autenticadas |
| `user` 100/min | usuários autenticados        |
| `login` 5/min  | `/auth/token/` e `/auth/token/refresh/` (anti força bruta) |

Configurada em `settings.py` (`DEFAULT_THROTTLE_*`) + `ScopedRateThrottle`
nas views de token. **Segurança mínima:** autenticação JWT exigida nas
escritas, `SECURITY_MIDDLEWARE` ativo e segredos via `.env`.

### Paginação e filtros

- **Paginação:** `PageNumberPagination` global (`PAGE_SIZE=20`) → respostas
  `{count, next, previous, results}` (validação de página inexistente → 404).
- **Filtros de domínio** (`ItemFilter` em `api/core/filters.py`):
  `?category=<id>`, `?is_active=true`, `?min_price=`, `?max_price=`.
  `category` usa `NumberFilter` sobre `category_id`: id inexistente → 200
  com lista vazia (evita 400 para catálogo público).
- **Busca livre:** `?search=iphone` (name/brand/model/sku em Item; name/slug
  em Category).
- **Ordenação:** `?ordering=-price`, `-created_at`, etc.

### Segredos no `.env`

`.env` é gitignored **(nunca versionado)**; `settings.py` e o compose leem:
`DJANGO_SECRET_KEY`, `JWT_SIGNING_KEY` e `DJANGO_DEBUG` (o `.env.example`
documenta os placeholders). Gere valores fortes com:

```powershell
python -c "from django.utils.crypto import get_random_string; print(get_random_string(50))"
```

### Matriz de status validada (ambiente conteinerizado)

| Cenário                              | Status |
| ------------------------------------ | ------ |
| Healthcheck                          | 200    |
| Login admin / user (credenciais corretas) | 200 |
| Login com credencial errada          | 401    |
| Refresh / verify                     | 200    |
| GET list/detail sem token            | 200    |
| POST sem token (categorias e itens)  | 401    |
| POST com user / admin                | 201    |
| POST inválido (preço negativo)       | 400    |
| PUT/PATCH/DELETE com user            | 403    |
| PUT/PATCH com admin                  | 200    |
| DELETE com admin                     | 204    |
| Burst de login (>5/min)              | 429    |
| Página de listagem inexistente       | 404    |

Coleção exportada para teste:
`collections/synapseshop_aula7.postman_collection.json` (variáveis
`base_url`, `token_admin`, `token_user` e `refresh_admin` — os logins
preenchem os tokens automaticamente).


## Cache-aside com Redis (Aula 8)

### Redis na orquestração

O serviço `redis:7-alpine` entra no `docker-compose.yml` com `db 1` exclusivo
para o cache da API (o `db 0` fica livre para as aulas seguintes), sem
persistência (o cache é descartável por definição) e com `healthcheck`. A API
só sobe depois que o Redis responde a `PING`:

```yaml
redis:
  image: redis:7-alpine
  ports: ["6379:6379"]
  command: ["redis-server", "--save", "", "--appendonly", "no"]
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
```

O backend é o **nativo do Django** (`django.core.cache.backends.redis.RedisCache`,
disponível desde o Django 4.0) sobre o cliente `redis-py` — que já fala
`SETEX` (TTL) e `INCR` (o contador de geração da invalidação). Isso dispensa
uma dependência extra como o `django-redis`.

Chaves reais no Redis (prefixo `synapseshop` + db + nome do app):

```
synapseshop:1:item:list:g1:44136fa355b3     listagem, geração 1, filtro A
synapseshop:1:categoria:list:geracao        contador de geração
synapseshop:1:item:2                        detalhe simples
synapseshop:1:item:2:detalhes               consulta pesada
```

### O padrão cache-aside

`api/core/cache.py` centraliza o fluxo em um único ponto
(`consultar_com_cache`), usado pelas viewsets:

1. **MISS** — lê o Redis; sem valor, executa a consulta no PostgreSQL
   (serializer + renderer), grava o resultado com TTL e devolve;
2. **HIT** — devolve o payload guardado, sem tocar no banco;
3. **Falha no Redis** — loga `CacheDegradado` e devolve a resposta do banco
   (fail-open): o cache é otimização, não pode virar ponto único de falha.

Endpoints instrumentados: listagem de itens, detalhe simples de item, consulta
pesada `GET /api/v1/items/{id}/detalhes/` e listagem de categorias — os dois
primeiros tipos exigidos pela spec ("listagem" e "acesso a dados específicos").
A consulta pesada existe para dar sentido ao cache: ela cruza 4 `SELECT`s
(`COUNT`/`AVG`/`MIN`/`MAX` da categoria, até 3 itens mais caros e até 3 mais
recentes), custo que some no cache depois do primeiro acesso.

### Chaves e TTL

| Chave                       | Conteúdo                            | TTL  |
| --------------------------- | ----------------------------------- | ---- |
| `item:list:g{ger}:{hash}`   | página de listagem (JSON serializado) | 60 s |
| `categoria:list:g{ger}:{hash}` | página de listagem               | 60 s |
| `item:{id}`                 | detalhe simples                     | 300 s |
| `item:{id}:detalhes`        | consulta pesada                     | 300 s |

- As **listagens** levam um contador de geração (`item:list:geracao`) no nome da
  chave, e o `{hash}` é o *fingerprint* dos parâmetros que alteram o resultado
  (página, ordenação, busca, filtros). Duas listagens com filtros diferentes
  nunca colidem.
- Os **detalhes** não levam geração: a chave é derivada do `id` e a
  invalidação é por `delete`.
- TTLs são ajustáveis por `CACHE_TTL_LIST` / `CACHE_TTL_DETAIL`; são apenas uma
  rede de segurança, porque quem garante a correção dos dados é a invalidação
  por evento.
- `CACHE_ENABLED=false` desliga tudo (nenhuma leitura/escrita) — é o switch do
  baseline de desempenho.

### Invalidação por evento de domínio

A invalidação é feita por **sinais do Django** (`api/core/signals.py`), depois
do commit da transação (`transaction.on_commit`), para nunca invalidar algo que
ainda pode ser revertido por um `rollback`:

| Evento                        | Efeito                                                                                       |
| ----------------------------- | -------------------------------------------------------------------------------------------- |
| `ItemCriado` / `ItemAtualizado` / `ItemRemovido` | `delete` em `item:{id}` e `item:{id}:detalhes` + `INCR` em `item:list:geracao` |
| `CategoryCriada` / `CategoryAtualizada` / `CategoryRemovida` | `delete` em `categoria:{id}` + `INCR` em `categoria:list:geracao` **e** em `item:list:geracao` |
| `Item` com categoria alterada | idem `ItemAtualizado`                                                                        |

Dois detalhes que valem registro:

- **Listagens são invalidadas por geração, não por chave.** Sem isso, seria
  preciso varrer o Redis procurando `item:list:*` — o Django não oferece
  "delete por padrão de chave". Com o contador, um `INCR` invalida todas as
  listagens de uma vez e as chaves antigas expiram sozinhas (60 s).
- **Alterar a categoria invalida a listagem de itens**, não só a de categorias:
  a listagem de itens embute o nome da categoria, então o dado está
  desnormalizado em dois lugares e a invalidação precisa cobrir os dois.

### Métricas de eficácia (hit rate)

`GET /api/v1/cache/metrics/` (somente `admin`) expõe
`hits / (hits + misses)` por namespace e no total, além de `bypasses`,
`erros` e `invalidacoes`:

```json
{
  "cache_habilitado": true,
  "redis": {"url": "redis://***@redis:6379/1", "key_prefix": "synapseshop",
            "ttl_lista_s": 60, "ttl_detalhe_s": 300},
  "total": {"lookups": 417, "hits": 413, "misses": 4, "bypasses": 0,
            "erros": 0, "invalidacoes": 0, "hit_rate": 0.9904},
  "namespaces": {"item:list": {"lookups": 105, "hits": 104, "misses": 1,
                               "bypasses": 0, "erros": 0, "hit_rate": 0.9905}}
}
```

Os mesmos eventos saem em **log estruturado JSON** (logger `core.cache`), o que
permite ver o ciclo `miss → preenchimento → hit` ao vivo:

```powershell
docker compose logs -f api
```

```json
{"timestamp": "...", "level": "INFO", "logger": "core.cache", "evento": "CacheLookup",
 "namespace": "item:list", "chave": "item:list:g1:44136fa355b3", "resultado": "miss",
 "ttl_s": 60, "latencia_ms": 0.369, "preenchimento_ms": 33.822, "mensagem": "cache miss"}
{"timestamp": "...", "level": "INFO", "logger": "core.cache", "evento": "CacheLookup",
 "namespace": "item:list", "chave": "item:list:g1:44136fa355b3", "resultado": "hit",
 "latencia_ms": 0.519, "mensagem": "cache hit"}
{"timestamp": "...", "level": "INFO", "logger": "core.cache", "evento": "ItemAtualizado",
 "namespace": "item:detalhes", "chave": "item:2:detalhes", "resultado": "invalidacao",
 "motivo": "registro alterado: chave item:2:detalhes removida", "mensagem": "cache invalidacao"}
```

### Desempenho medido: antes x depois

Medido por `scripts/measure_cache.py` (HTTP de ponta a ponta, biblioteca
padrão), no mesmo ambiente dos dois lados: **501 itens e 4 categorias**
(26 páginas de 20), 100 requisições por endpoint, 3 de aquecimento, um cliente
sequencial. As taxas de throttling foram elevadas no entorno da medição para
que nenhum 429 contaminasse a amostra.

```powershell
# baseline (comportamento pré-Aula 8)
$env:CACHE_ENABLED = "false"; docker compose up -d api
.venv\Scripts\python.exe scripts\measure_cache.py --requests 100 --label "sem cache"

# com cache
$env:CACHE_ENABLED = "true"; docker compose up -d api
.venv\Scripts\python.exe scripts\measure_cache.py --requests 100 --label "com cache"
```

| Endpoint                   | Média sem cache | Média com cache | Δ média | p95 sem cache | p95 com cache | RPS sem cache | RPS com cache |
| -------------------------- | --------------- | --------------- | ------- | ------------- | ------------- | ------------- | ------------- |
| Listagem de itens          | 58,30 ms        | 33,50 ms        | −42,5 % | 87,79 ms      | 49,73 ms      | 17,1          | 29,7 (+73,7 %) |
| Detalhe de item            | 39,61 ms        | 31,63 ms        | −20,1 % | 61,14 ms      | 54,78 ms      | 25,2          | 31,5 (+25,0 %) |
| Detalhes (consulta pesada) | 53,01 ms        | 27,76 ms        | −47,6 % | 71,50 ms      | 39,58 ms      | 18,8          | 35,9 (+91,0 %) |
| Listagem de categorias     | 43,38 ms        | 29,90 ms        | −31,1 % | 68,83 ms      | 46,58 ms      | 23,0          | 33,3 (+44,8 %) |
| **Média dos 4 endpoints**   | **48,58 ms**    | **30,70 ms**    | **−36,8 %** | —         | —             | **21,0**      | **32,6 (+55,1 %)** |

Hit rate da rodada com cache: **99,0 %** (413 hits / 417 lookups; os 4 misses
são exatamente a primeira requisição de cada namespace). As colunas `1ª fria`
(primeira requisição, ainda sem chave) e `média ss` (regime permanente) ficam
no relatório do script.

Como ler estes números com honestidade:

- o ganho é de **regime permanente**; a primeira requisição de cada chave paga
  o MISS (banco + escrita no Redis) e é, em geral, mais cara que sem cache —
  é o preço de entrada do cache;
- o RPS é de **um cliente sequencial**: serve para comparar os dois cenários
  nas mesmas condições, não como limite de capacidade;
- o ganho é menor no detalhe simples (39,6 → 31,6 ms) porque ele já é um único
  `SELECT` por `pk`; o cache economiza o little round-trip ao banco, mas não
  há agregação cara para evitar.

### Modo degradado: Redis fora do ar

Com o Redis parado, a API **continua respondendo 200** — todas as requisições
caem no banco e cada falha é registrada (`CacheDegradado` / `erro` nas
métricas). O custo é a latência: como o time-out de socket é de 1 s, cada
requisição leva cerca de 3,4 s até o banco responder. A leitura é
intencionalmente rápida e barulhenta em vez de silenciosa, para que a queda do
cache apareça no log e no dashboard.


## Mensageria assíncrona (Aula 9)

A Aula 9 introduz o **processamento assíncrono por eventos** para o fluxo de
pedidos. A API deixa de esperar o processamento terminar: cria o pedido,
publica o evento `PedidoCriado` com publisher confirms e responde **201**. Um
**worker** independente consome e avança o estado para `processado` (ou `falha`),
com **idempotência ponta a ponta** e **DLQ** para falhas irrecuperáveis.

O broker da Aula 9 é o **RabbitMQ**, e ele continua no projeto como
implementação alternativa (profile `rabbitmq`). A Aula 10 troca o padrão para
o **Kafka** — ver "Apache Kafka: partições, offsets e DLQ (Aula 10)". A escolha é
feita por uma variável de ambiente:

```powershell
# Kafka (padrão)
docker compose up -d

# RabbitMQ da Aula 9
$env:MENSAGERIA_BROKER='rabbitmq'
docker compose --profile rabbitmq up -d rabbitmq worker
```

O dispatcher (`core/messaging/broker.py`) é o único ponto que sabe qual é o
broker: a view, o worker e o replayer pedem "publique"/"consuma" e nunca citam
Kafka ou RabbitMQ. É o que permite as duas implantações rodarem com o mesmo
código Django, models e migrações — sem duplicar ORM.

### Ambiente: os dois conjuntos de serviços

| Serviço        | Imagem                             | Função                                                    |
| -------------- | ---------------------------------- | --------------------------------------------------------- |
| `kafka`        | `apache/kafka:3.9.1`               | Broker Kafka em KRaft single-node. Listener interno `kafka:29092`, externo `localhost:9092`. |
| `worker-kafka` | build do Dockerfile                | Consumidor Kafka + replayer de retry. Sobe após `api` e `kafka` saudáveis. |
| `rabbitmq`     | `rabbitmq:3.13-management-alpine`  | Broker AMQP 0-9-1 (profile `rabbitmq`), UI em `http://localhost:15672`. |
| `worker`       | build do Dockerfile                | Consumidor RabbitMQ (profile `rabbitmq`). |

Os volumes `kafkadata` e `rabbitmqdata` mantêm os dados se o container reiniciar.

Os serviços de worker **não** têm `container_name` de propósito: é o que permite
`docker compose up -d --scale worker-kafka=3` (um `container_name` fixo impede
escalar, porque o segundo container não teria nome livre).

A API **não** declara `depends_on` do broker: ela sobe com ou sem mensageria,
porque o pedido precisa ser gravado mesmo quando o broker está fora (ver
"Recuperação quando o broker está fora"). Quem depende do broker é o worker.

### Contrato do evento `PedidoCriado` (v1)

O evento é definido em [`docs/contracts/pedido_criado.md`](docs/contracts/pedido_criado.md). Campos mínimos de negócio, `idempotency_key`, `publicado_em` (epoch ms) e valores monetários como **string** (evita perda de precisão com Decimal em JSON).

Exemplo resumido:

```json
{
  "evento": "PedidoCriado",
  "versao": 1,
  "evento_id": "0f9c1e6c-2c1f-4a0a-9a3f-6b1d2c4e5f70",
  "idempotency_key": "9f2c...64 hex",
  "origem": "synapseshop-api",
  "ocorrido_em": "2026-09-30T12:00:00.000Z",
  "publicado_em": 1759243200123,
  "pedido": {
    "id": 42,
    "usuario_id": 2,
    "status": "pendente",
    "total": "1299.90",
    "itens": [
      {"sku": "MED-0499", "quantidade": 2, "preco_unitario": "1998.00"}
    ]
  }
}
```

Validação estrita no consumidor: payload inválido → **DLQ imediata** (falha terminal).

### Idempotência (duas barreiras)

A chave viaja no evento e é usada em **duas camadas independentes**:

1. **Janela de idempotência (Redis db 0)** — `core/messaging/dedupe.py`. Usa `SET key NX EX ttl` (TTL 86.400 s, configurável por `DEDUPE_TTL_SEGUNDOS`). `reservar()` retorna `False` se a chave já existe → mensagem duplicada, `ack` sem aplicar efeito. Em caso de falha do Redis, o código é **fail-open** (processa e deixa o banco proteger). No caminho de falha, `liberar()` apaga a chave para que a reentrega consiga reprocessar.
2. **Update condicional (PostgreSQL)** — no consumidor: `UPDATE Pedido SET status='processado', ... WHERE pk=? AND idempotency_key=? AND status IN (pendente_publicacao,pendente,falha)`. Se 0 linhas afetadas: (a) já `processado` → duplicata real (log `PedidoDuplicado`, motivo "pedido já estava processado"); (b) chave diferente ou pedido inexistente → `MensagemIncorreta` → **DLQ** (terminal). Esta é a **autoridade final** (sobrevive mesmo com TTL expirado ou Redis indisponível).

A chave de idempotência no POST segue precedência: **header `Idempotency-Key`** (se <=64) ou **SHA-256 canônico** (usuário + itens ordenados por SKU + total). Um reenvio com a mesma chave devolve **HTTP 200** com `"evento": {"duplicado": true, "motivo": "pedido já existente"}` (ou 409 se o corpo for diferente).

### Reentregas, backoff e DLQ

Topologia declarada por `core/messaging/topologia.py`:

```
exchange pedidos (topic) --routing key pedido.criado--> pedidos.criados
                                                         │ DLX pedidos.dlx
exchange pedidos.retry (direct) --retry.1/.2/.3--------> pedidos.criados.retry.N (TTL 5/15/45 s)
                                                         │ DLX pedidos (volta à principal)
exchange pedidos.dlx (direct)   --pedido.criado--------> pedidos.criados.dlq (terminal, sem TTL)
```

Política:

- Tentativa inicial = 0 (header **`x-tentativa`**). Em exceção recuperável, republica para retry `{tentativa+1}` com TTL e `ack` da original.
- **3 reentregas** após a inicial (total até 4 passagens). Configurável por `PEDIDO_MAX_REENTREGAS` e `PEDIDO_BACKOFF_SEGUNDOS` (5,15,45).
- Ao esgotar (`tentativa >= max_reentregas`) ou em falha terminal (`ContratoInvalido`, `MensagemIncorreta`, política inconsistente), o pedido é marcado como `status = falha`, a mensagem vai para `pedidos.criados.dlq` e é `ack` — **nunca** reentregada infinitamente.

**Simulação de falha (validação ponta a ponta):** `POST /pedidos/` aceita `X-Simular-Falha: 1` **somente** se `PEDIDO_PERMITIR_SIMULACAO_FALHA=true`. O flag é gravado em `Pedido.simular_falha` e lido **do banco** pelo consumidor: ao processar, se verdadeiro, levanta `FalhaInjetada` (exceção recuperável), forçando a escada completa até a DLQ. Isso prova, com um pedido real e logs por tentativa, que a política de backoff e a DLQ funcionam conforme o desenho.

### Recuperação de publicações falhas

Se o broker estiver indisponível no momento do POST, o `publish` levanta `PublicacaoFalhou` (inclusive para `OSError`/DNS — evita virar 500). A view responde **HTTP 503** com corpo contendo `pedido_id`, `status: pendente_publicacao`, `idempotency_key` e o erro. O comando `python api/manage.py republicar_pedidos` varre pedidos em `pendente_publicacao`, republica seus eventos (publisher confirms) e, só depois do confirm, move-os para `pendente`. Também aceita `--pedido`, `--limit`, `--dry-run`. O idempotente: reenviar o POST com a mesma `Idempotency-Key` enquanto o broker está fora devolve **HTTP 200** com `evento.duplicado = true` e o pedido permanece em `pendente_publicacao`.

### Observabilidade (comum aos dois brokers)

- **Logs JSON** (logger `core.messaging`): a lista completa de eventos está na
  seção da Aula 10 (45 tipos) e em `docs/contracts/pedido_criado.md`; os campos
  são `evento_id`, `pedido_id`, `chave_idempotencia`, `tentativa`,
  `atraso_fila_ms`, `duracao_ms` (e `particao`/`offset`/`espera_ms` no Kafka).
- **Métricas em memória** (`core.messaging.metricas`): `recebidas`, `processadas`, `duplicadas`, `falhas`, `reentregas`, `dlq`, `invalidas`.
- **Medição ponta a ponta**: `scripts/measure_messaging.py` (stdlib) faz POST autenticado com `Idempotency-Key` explícita, aguarda `processado` por polling com intervalo adaptativo e reporta: latência **POST** (publisher confirm) e **publicação→processado** (baseada em `evento.publicado_em`), idempotência (3 reenvios), escada de reentrega com timestamps por tentativa, e profundidade das filas via Management API (`:15672`). Usa sessão JWT com renovação automática e pode `--purgar` as filas antes da medição.

**Medições reais (execução local, 20 pedidos + idempotência + DLQ):**

| Métrica | n | média | p50 | p95 | máx |
|---|---|---|---|---|---|
| POST (publisher confirm) | 20 | 78,83 ms | — | 101,76 ms | 105,45 ms |
| publicação → processado | 20 | 82,35 ms | 75 ms | 124 ms | 172 ms |

**Idempotência:** 3 reenvios com a mesma `Idempotency-Key` → **HTTP 200**, mesmo `pedido_id`, `evento.duplicado = true` (idempotente).

**Escada de reentrega (X-Simular-Falha):** tentativas registradas em `t+0,0s` (tentativa 0→1), `t+6,1s` (1→2), `t+21,3s` (2→3), `t+66,8s` (3→DLQ) — correspondendo aos degraus **5 s / 15 s / 45 s**. Pedido terminou em `status=falha`, mensagem na `pedidos.criados.dlq`. Após a leitura, as filas ficaram: `pedidos.criados.dlq` com 1 mensagem pronta (evidência da DLQ) e as demais vazias.

> Esses dois blocos de medições são da **Aula 9 (RabbitMQ)** e ficam aqui como
> linha de base. A Aula 10 repetiu a medição no Kafka, e os números do Kafka são
> os da seção seguinte — as duas tecnologias não são diretamente comparáveis
> linha a linha porque a topologia, a latência de confirmação e o mecanismo de
> reentrega são diferentes por desenho.


## Apache Kafka: partições, offsets e DLQ (Aula 10)

A Aula 9 provou o fluxo assíncrono sobre **RabbitMQ** e mediu latência. A Aula 10
trocou o broker: agora a implementação é **Apache Kafka**, que é o que a spec
pede, e a topologia é a do Kafka (tópico + partições + offsets confirmados), não a
equivalência AMQP. RabbitMQ continua disponível por profile para comparação.

### O que mudou em relação à Aula 9

| Item da spec                                | Como está implementado no Kafka                              |
| ------------------------------------------- | ------------------------------------------------------------ |
| Tópico e partições para paralelismo         | `pedidos.criados` com **3 partições**, chave = `str(pedido.pk)` |
| Retenção configurável                       | `retention.ms` por tópico (7 dias no principal, 30 dias na DLQ) |
| Consumidor com `ack` manual                 | `enable.auto.commit=false` + `commit()` **depois** do efeito  |
| `acks=all` / publisher confirm              | `acks=all`, `enable.idempotence=true`, `flush()` antes do 201 |
| Consumer group (partição por consumidor)    | `synapseshop-pedidos` — cada membro fica dono de uma partição |
| Dead letter                                 | tópico terminal `pedidos.criados.dlq`, sem consumidor         |
| Backoff escalonado                          | tópicos `pedidos.criados.retry.1/2/3` com retenção 610/630/690 s |

Duas decisões que valem registro:

* **A chave de produção é o `pedido_id`.** Assim todos os eventos do mesmo pedido
  caem na mesma partição, e a ordem dos eventos de um pedido é preservada — a
  garantia que a partição dá em vez de dar ordem global.
* **O replayer usa tópico de retenção, não `sleep`.** O degrau de espera é o
  `retention.ms` do tópico de retry: a mensagem fica lá pelo tempo do backoff e
  some sozinha. Não há timer no worker, então reiniciar o worker não reinicia a
  espera. Um `sleep(45)` seria mais simples e perderia a mensagem se o processo
  morresse.

### Como as medições foram feitas

```powershell
# com 1 consumidor
docker compose up -d
.venv\Scripts\python.exe scripts\measure_messaging.py --purgar --pedidos 20 `
    --duplicatas 3 --forcar-falha 1 --carga 60 --concorrencia 8 --inspecionar-dlq

# com 3 consumidores concorrentes
docker compose up -d --scale worker-kafka=3
.venv\Scripts\python.exe scripts\measure_messaging.py --purgar --pedidos 20 `
    --duplicatas 3 --forcar-falha 1 --carga 60 --concorrencia 8 --inspecionar-dlq

# estado do broker: tópicos, retenção, offsets confirmados e lag por partição
docker compose exec api python api/manage.py declarar_topicos_kafka --json

# resumo do log transacional (não precisa da API no ar)
docker compose logs --no-color --no-log-prefix worker-kafka > logs_worker.jsonl
.venv\Scripts\python.exe scripts\measure_messaging.py --analisar-logs logs_worker.jsonl
```

`scripts/measure_messaging.py` detecta o broker em `/health` e troca só as etapas
de broker: no Kafka elas delegam aos management commands (o cliente Python do
broker só existe na imagem da API), no RabbitMQ leem a management API. Latência,
carga e análise de log são o mesmo código nos dois casos.

Quatro regras metodológicas que mudam o número final:

- **`DRF_USER_RATE` precisa estar no mesmo comando do `docker compose up`.**
  O `docker-compose.yml` injeta `${DRF_USER_RATE:-100/min}`; sem a variável no
  ambiente, qualquer `up` posterior recria a API no padrão. Ver "Defeitos de
  medição encontrados".
- **A latência é medida por *polling*** (`GET /pedidos/{id}`), com intervalo
  de 0,2 s no primeiro ciclo. Em fluxo feliz a latência é da ordem de dezenas de
  milissegundos, ou seja, do mesmo tamanho do intervalo — o número honesto é
  "dezenas de ms", não o valor exato.
- **O `--carga` do script mede a vazão do *pipeline inteiro*, e ele é limitado
  pelo POST.** O `GET /pedidos/{id}` custa ~0,8 s nesta pilha (DRF + banco), e
  o `POST` com `acks=all` espera o disco do broker. Uma carga de 30 pedidos com
  8 em paralelo mede 9,3 ped/s na publicação — e esse teto é da API, não da
  mensageria.
- **A vazão do *consumidor* tem que ser medida pelos timestamps do log do
  worker**, não pelo relógio de um script — ver a seção de paralelismo abaixo.

### Latência (ponta a ponta, com 1 consumidor)

Medida em repouso, sem carga, com 10 pedidos:

| Métrica                                   | valor                            |
| ----------------------------------------- | -------------------------------- |
| Latência publicação → `processado`        | média **152 ms**, p50 **100 ms**, p95 640 ms |
| POST (inclui o `acks=all` do broker)      | média 162 ms, p95 659 ms         |
| `POST /pedidos/` sob carga (n = 30)       | média 761 ms, p95 967 ms          |
| Idempotência (2 reenvios da mesma chave)  | 200, mesmo `id`, `duplicado: true` |
| Respostas 429 absorvidas                 | 0                                |

O POST custa mais que a latência do pipeline inteiro: ele espera o
`acks=all`, que é fsync no disco do broker, e é essa espera que o cliente sente.
Já a fila assíncrona entrega em milissegundos depois disso.

### Vazão e paralelismo: 1 versus 3 consumidores

O número vem dos **timestamps do log do worker**: a vazão é a distância entre a
primeira e a última `MensagemRecebida` de *uma* rajada, identificada pelo
prefixo da `chave_idempotencia`. Nenhum relógio de script entra na conta.

> **Por que não cronometrar de fora.** A primeira versão media o drain com um
> script que lia o offset confirmado do grupo, e o número estava **errado por
> construção**: dividia a soma *acumulada* dos offsets das 3 partições pelo tempo
> (`ultimo/dt`), um valor que cresce a cada rodada. Pior, o relógio começava
> quando o script subia — e o worker começa a drenar no instante em que entra no
> grupo, então numa rajada de 600 o script leu a linha de base **530 mensagens
> depois** do início e reportou 0,3 msg/s para um drain que já tinha terminado.
> O log do worker não sofre desse erro: o instante de cada mensagem é o registro
> do próprio broker, e a rajada é identificada sem ambiguidade.

Método: publica-se uma rajada com o worker **parado** (600 pedidos), sobe-se o
worker, e mede-se o span da rajada no log. As duas pernas foram executadas
encostadas, na mesma sessão e com a mesma imagem.

| Rajada de 600 mensagens        | 1 consumidor | 3 consumidores |
| ------------------------------ | ------------ | -------------- |
| Span da rajada no log         | **8,53 s**   | **9,68 s**     |
| Vazão                          | **70,2 msg/s**| **61,9 msg/s** |
| `duracao_ms` p50 / p95         | 10,7 / 31,3 ms | 9,6 / 45,6 ms |
| Mensagens por partição         | 197/188/215  | 195/200/205    |
| Processadas duas vezes         | 0            | 0              |
| `OffsetCommitFalhou`           | 0            | 0              |

**3 consumidores foram mais lentos que 1** (61,9 contra 70,2 msg/s, −12%), e não
3× mais rápidos. A partição-por-consumidor funciona — as 600 mensagens se
distribuem pelas 3 partições (195/200/205) e nenhuma é processada duas vezes —
mas **nesta configuração o paralelismo não paga**.

O motivo provável é o custo fixo de cada consumidor novo entrar no grupo: com 3
containers o grupo precisa coordenar 3 rebalances, e o `duracao_ms` máximo da
rajada sobe de 114 ms para **2.881 ms** — quase 3 s em que uma partição ficou
parada esperando o rebalance. Em uma rajada de 8,5 s, esses segundos fixos
comem o ganho do paralelismo. Soma-se a isso o commit síncrono por mensagem
(medido direto contra o broker: p50 1,30 ms, p95 2,59 ms; o mesmo lote sem
commit vai de 408 para 1017 msg/s), que serializa no broker e não paraleliza.

> **Registro honesto:** a primeira medição desta tabela dio 167 → 223 msg/s
> (ganho de 1,33×) e a conclusão "o broker single-node satura a 227% de CPU".
> **Os dois números estavam errados** — o primeiro pela divisão do offset
> acumulado, o segundo porque o `docker stats` foi amostrado **depois** do drain
> já ter terminado. A tabela acima é a medição corrigida.

> **Só 3 consumidores podem trabalhar.** `pedidos.criados` tem 3 partições, e o
> broker entrega cada partição inteira a um membro só. Com `--scale
> worker-kafka=5`, dois containers entram no grupo, não recebem partição e ficam
> ociosos gastando memória. Para mais paralelismo é preciso aumentar as
> partições do tópico — e isso **não pode ser feito depois**: Kafka só aceita
> aumentar, nunca reduzir.

### Onde está o gargalo

Do log transacional da rajada de 1 consumidor (600 mensagens):

| Métrica do log                        | média   | p50     | p95     |
| ------------------------------------ | ------- | ------- | ------- |
| `duracao_ms` (trabalho no consumidor) | 13,9 ms | 10,7 ms | 31,3 ms  |

Cada mensagem consome **~14 ms** de trabalho, dos quais ~1,3 ms são o commit
síncrono — **~10% do tempo**. O `atraso_fila_ms` alto na rajada é proposital: 600
pedidos publicados antes de o worker subir, para haver o que drenar. Não é
latência de sistema.

### Idempotência × latência × throughput

Os três requisitos puxam em direções opostas, e o desenho escolhe posição:

| Decisão                                | Ganho                                        | Custo                                        |
| -------------------------------------- | -------------------------------------------- | -------------------------------------------- |
| Dedupe no Redis antes do efeito        | evita transação e `UPDATE` no banco         | 1 ida e volta ao Redis por mensagem (~1 ms)  |
| Dedupe **só** no banco (`UPDATE` cond.)| dispensa o Redis no caminho crítico          | transação no banco para toda mensagem         |
| Backoff 5/15/45 s em retenção de tópico | não trava o consumidor com retentativa      | falha terminal demora ~65 s para ser visível |
| 1 mensagem por `poll()`                | processamento por mensagem isolado           | 1 consumidor processa 1 por vez               |
| `acks=all` + `enable.idempotence`      | nenhum 201 "fantasma"                        | POST espera o disco do broker                 |

O que a medição mostra é que **a idempotência é barata** (uma ida e volta ao
Redis, ~1 ms de um total de ~10 ms de trabalho no consumidor) e que **o custo
real da consistência está em esperar o resultado durável antes de responder
201** — se a API respondesse antes do confirm, o POST cairia para ~1 ms e o
cliente passaria a correr o risco de um pedido que nunca existiu.

### Dedupe fail-open: Redis fora do ar

Com `docker compose stop redis`, e o pipeline inteiro ainda funcionando:

| Métrica                        | Redis no ar | Redis fora do ar |
| ------------------------------ | ----------- | ---------------- |
| Pedidos processados            | 10/10       | 10/10            |
| Latência média                 | ~70 ms      | **3.437 ms**     |
| Idempotência (3 reenvios)      | 200, mesmo id | 200, mesmo id   |
| Eventos de degradação          | —           | `DedupeDegradado`, `DedupeNaoConfirmado` |

O comportamento é o desejado: **a janela do Redis é otimização, o banco é a
autoridade**. Com o Redis fora, o consumidor registra
`DedupeDegradado: "fail-open: o UPDATE condicional no banco continua
garantindo o efeito único"` e segue; o `UPDATE` condicional do PostgreSQL
continua impede qualquer efeito duplicado (os 3 reenvios devolveram o mesmo
pedido, sem novo evento). O preço é a **latência**: cada mensagem espera o
time-out do Redis (resolução de nome, ~1,7 s, duas vezes por mensagem) antes de
seguir. Fail-open compra disponibilidade ao preço da latência — que é
exatamente a escolha que a spec pedia para medir.

> O experimento acima é anterior ao contador `dedupe_degradado`, então a
> evidência dele são os eventos de log. Hoje a mesma degradação também aparece
> como número no snapshot do `WorkerEncerrado` — dá para responder "quantas
> vezes a janela não pôde ser usada" sem contar warnings.

### At-least-once: worker morto e rebalance

No Kafka, a garantia é a mesma da Aula 9 mas o nome muda: `basic_ack()` vira
`commit(message=…)`, e o que antes era "a fila devolveu" agora é "a partição
voltou para o grupo". O efeito no banco é gravado antes do commit, então uma
queda entre os dois devolve a mensagem em vez de perdê-la.

Três cenários medidos:

| Cenário                                                  | Resultado |
| -------------------------------------------------------- | --------- |
| `docker compose stop worker-kafka` no meio da rajada      | offset confirmado alcançou a marca d'água, **lag final 0** |
| `--scale worker-kafka=3` → `--scale worker-kafka=1` durante consumo | rebalance com partições mudando de dono; **0 `OffsetCommitFalhou`** |
| `docker compose kill -s KILL worker-kafka`                | offset volta ao último confirmado; sem perda |

O caso do rebalance mereceu uma correção de código. Ao mudar o número de
consumidores durante o consumo, o broker invalida a `generation_id` e recusa o
commit em voo com `ILLEGAL_GENERATION` — o comportamento **documentado** do
protocolo, porque a partição já tem outro dono e quem confirma o offset é ele.
Ainda assim o log registrava isso como ERROR vermelho a cada rebalance, parecendo
defeito no consumer. Hoje `_confirmar()` distingue os dois casos: rebalance sai
como `OffsetCommitIgnorado` em INFO com o motivo explícito, e só falha real de
commit continua em ERROR (`OffsetCommitFalhou`). Depois da correção, a rodada
com rebalance forçado no meio do consumo deu **0** falhas.

### Reset de offset: reprocessar o histórico

`manage.py declarar_topicos_kafka --resetar-offsets` volta o grupo para
`earliest` (ou `latest`), que é a operação que não existe em AMQP:

```powershell
# o grupo precisa estar VAZIO, senão o comando nao faz nada (ver abaixo)
docker compose stop worker-kafka
docker compose exec api python api/manage.py declarar_topicos_kafka `
    --resetar-offsets earliest --grupo synapseshop-pedidos
docker compose up -d worker-kafka
```

> **O reset só vale com o grupo parado.** Com o worker no ar o comando **retorna
> sucesso e não move nada**: o broker aceita o `AlterOffsets` para um grupo
> estável, mas o consumidor já tem a posição em memória e segue dela. Medido
> aqui: com 3 workers no grupo, o reset reportou `-> earliest` e os offsets
> continuaram no fim do log (1379/1355/1386 = watermark), com zero mensagens
> reprocessadas. Parando o grupo, o mesmo comando derrubou os três offsets para
> 0 (4120 mensagens pendentes) e o replay aconteceu de fato. **Always confira o
> offset depois do reset** — `declarar_topicos_kafka --json` mostra
> `commit`/`lag` por partição.

**Replay validado de ponta a ponta.** Depois do reset com o grupo vazio, o worker
releu as 4120 mensagens da retenção:

| Evento durante o replay                     | Quantidade |
| ------------------------------------------- | ---------- |
| `MensagemRecebida`                          | 4.135      |
| `PedidoDuplicado` (idempotência segurou)    | 4.064      |
| `PedidoFalha` / `PedidoDlq`                 | 57 / 14    |

E o banco **não mudou nada**: `processado = 4996` e `falha = 24` antes e depois,
idênticos. É a prova de que o efeito é único mesmo com o histórico inteiro
reprocessado — o dedupe no Redis e o `UPDATE` condicional no banco absorveram.

Um detalhe que vale registrar: os `PedidoFalha`/`PedidoDlq` do replay **não são
defeito**. São os pedidos de E2E criados com `X-Simular-Falha`, que guardam
`simular_falha=True` no banco — ao serem relidos, o consumer levanta a falha
injetada de novo e a escada roda outra vez. O replay de um histórico que
contém falhas intencionais **repopula a DLQ** (aqui, de 6 para 20 mensagens).
Com um histórico só de sucesso, o replay é 100% `PedidoDuplicado`.

### Logs transacionais

O consumer e o produtor emitem **um JSON por evento** (logger `core.messaging`),
com campos estruturados que tornam a análise uma agregação, não um `grep`:

```json
{"timestamp": "2026-10-01T16:07:41.882Z", "level": "INFO", "logger": "core.messaging",
 "evento": "PedidoProcessado", "resultado": "ok", "evento_id": "574b5cd4-...",
 "chave_idempotencia": "aula10-carga-1790873-14", "pedido_id": 336,
 "fila": "pedidos.criados", "tentativa": 0, "atraso_fila_ms": 17.0, "duracao_ms": 8.87,
 "mensagem": "pedido processado"}
{"timestamp": "...", "level": "WARNING", "logger": "core.messaging",
 "evento": "DedupeDegradado", "resultado": "erro",
 "motivo": "fail-open: o UPDATE condicional no banco continua garantindo o efeito único",
 "erro": "ConnectionError: Error -2 connecting to redis:6379. Name or service not known.",
 "mensagem": "janela de deduplicação indisponível; seguindo sem ela"}
```

`--analisar-logs` agrega o arquivo em contagem de eventos, distribuição de
`duracao_ms`/`atraso_fila_ms`/`espera_ms`, trabalho por instância e **por
partição** (é o que produz o 114/96/90 acima). O pacote de mensageria emite
**45 tipos de evento**, e a lista foi conferida contra o código com um grep de
`"evento":` — não é contagem de memória:

| Grupo                | Eventos                                                                                          |
| -------------------- | ------------------------------------------------------------------------------------------------ |
| Ciclo da mensagem    | `MensagemRecebida`, `MensagemEncerrada`, `PedidoProcessado`, `PedidoDuplicado`, `PedidoFalha`, `PedidoDlq`, `ErroConsumo` |
| Publicação           | `PedidoPublicado`, `PedidoPublicacaoFalhou`, `ProdutorCriado`, `ProdutorFechando`                |
| Topologia            | `TopicosDeclarados`, `TopicosDescritos`, `TopicosPurgados`, `OffsetsResetados`                    |
| Offset               | `OffsetCommitFalhou`, `OffsetCommitIgnorado`, `ReentregaFalhou`, `GruposIndisponiveis`            |
| Falha de política    | `DlqFalhou`, `PoliticaInconsistente`                                                              |
| Dedupe               | `DedupeDegradado`, `DedupeNaoConfirmado`, `DedupeNaoLiberado`                                     |
| Replay               | `ReplayerIniciado`, `ReplayerConectado`, `ReplayerEncerrando`, `ReplayerEncerrado`, `ReplayerErro`, `ReplayerFalha`, `RetryLiberada`, `RetryRetomado`, `RetryAguardando`, `RetrySemTimestamp`, `ReplayerTopicoDesconhecido`, `ReplayerPausaFalhou`, `ReplayerRetomadaFalhou`, `ReplayerDevolucaoFalhou` |
| Ciclo de vida worker | `WorkerIniciado`, `WorkerEncerrando`, `WorkerEncerrado`, `WorkerInterrompido`, `WorkerLimiteAtingido`, `WorkerParando`, `WorkerSemConexao` |
| Dispatcher           | `BrokerDesconhecido`                                                                              |

`PedidoCriado` **não** aparece nessa lista: é o nome do contrato
(`contracts.EVENTO_PEDIDO_CRIADO`), não um evento de log — o evento de
publicação que o produtor emite é `PedidoPublicado`.

### Defeitos de medição encontrados (e corrigidos)

Os problemas mais sérios desta aula não foram no sistema de mensageria — foram
**no próprio instrumento de medição**, e vale registrá-los porque é o que
transforma um relatório em evidência:

1. **A API grava `falha` antes de publicar na DLQ.** A medição original usava
   `sleep(2)` entre "API disse `falha`" e "ler a fila". Capturado com snapshots
   finos, o instante do `falha` é `t+68,1s` com `DLQ=0, retry.3=1` — a mensagem
   ainda estava na última fila de retry. Com o sleep, o relatório ora diria
   `dlq=0`, ora `dlq=1`. **Corrigido**: `aguardar_mensagem_na_dlq()` pergunta ao
   broker até a mensagem aparecer, e reporta quanto esperou (7,92 s na rodada
   com Kafka, porque a mensagem estava na retenção do degrau 3).
2. **Medir vazão pelo relógio do próprio script mede o script.** A primeira
   tentativa publicava uma rajada e ficava fazendo `GET /pedidos/{id}` a cada
   ~20 ms. Resultado: **1,0 ped/s** com 1 consumidor. O log do worker da mesma
   janela provava 20/s (gap p50 de **46 ms** entre mensagens processadas). O
   `GET` custa ~0,8 s nesta pilha, então o instrumento era mais lento que a
   coisa medida. **Corrigido**: a vazão do consumidor é medida pelo **offset
   confirmado do grupo**, que é número do broker.
3. **O gerador publicava mais do que pedia.** Com o loop de publicação contando
   a cada iteração em vez de a cada `N`, a primeira rajada pediu 60 e publicou
   64 — e o relatório dizia "64/60", o que denuncia a falha mas só depois de
   ela estar no número. **Corrigido**: o gerador guarda a contagem por lock e
   o alvo vem da marca d'água lida depois da publicação, nunca de um contador
   paralelo.
4. **O intervalo dinâmico do Windows tem só 1000 portas.** A carga roda dentro
   do container (`docker compose exec`), porque o host abre e fecha conexões
   para `localhost:8000` tão rápido que esgota `10000-10999` e falha com
   `WinError 10048`.
5. **Throttling absorvido em silêncio.** O `docker compose up --scale worker=3`
   recriou a API com `DRF_USER_RATE` no padrão (100/min) porque a variável não
   existia naquele shell. 11 respostas 429 empurraram a latência média da carga
   para **53 s**, contra ~4,5 s na rodada limpa — e o relatório saía limpo.
   **Corrigido**: todo 429 é contado, e a execução sai com código 1 e um aviso
   se passar de `--tolerar-429` (padrão 0).
6. **`RemoteDisconnected` não é `URLError`.** Derrubar a API no meio da carga
   matava o harness com traceback. **Corrigido**: `OSError`/
   `http.client.HTTPException` entram na mesma fila de retentativa, em contador
   separado do 429.
7. **Rebalance registrado como falha de commit.** `ILLEGAL_GENERATION` no
   commit durante `--scale` é o protocolo funcionando, não defeito. Detalhado
   em "At-least-once: worker morto e rebalance".

### Comandos úteis (Aulas 9 e 10)

```powershell
# Estado do broker: tópicos, retenção, offsets confirmados e lag por partição
docker compose exec api python api/manage.py declarar_topicos_kafka

# Verificar o que ficou preso na DLQ (lê sem consumir)
docker compose exec api python api/manage.py inspecionar_dlq_kafka

# Devolver as mensagens da DLQ ao tópico principal (ação destrutiva)
docker compose exec api python api/manage.py inspecionar_dlq_kafka --reprocessar

# Logs do worker
docker compose logs -f worker-kafka

# Escalar consumidores (o service não tem container_name de propósito)
docker compose up -d --scale worker-kafka=3

# Recuperar pedidos em pendente_publicacao
docker compose exec api python api/manage.py republicar_pedidos --dry-run
docker compose exec api python api/manage.py republicar_pedidos

# Medição completa (latência, idempotência, vazão, DLQ, offsets)
.venv\Scripts\python.exe scripts\measure_messaging.py --purgar --pedidos 20 `
    --duplicatas 3 --forcar-falha 1 --carga 60 --concorrencia 8 --inspecionar-dlq

# Só a vazão, sem esperar a escada de reentrega (~65 s)
.venv\Scripts\python.exe scripts\measure_messaging.py --purgar --pedidos 0 `
    --duplicatas 0 --forcar-falha 0 --carga 60 --concorrencia 8

# Resumo do log transacional
docker compose logs --no-color --no-log-prefix worker-kafka > logs_worker.jsonl
.venv\Scripts\python.exe scripts\measure_messaging.py --analisar-logs logs_worker.jsonl

# Dedupe degradado (fail-open)
docker compose stop redis
.venv\Scripts\python.exe scripts\measure_messaging.py --purgar --pedidos 10 --duplicatas 3
docker compose start redis

# RabbitMQ da Aula 9, por profile (a API precisa nascer com o mesmo broker)
$env:MENSAGERIA_BROKER='rabbitmq'
docker compose --profile rabbitmq up -d rabbitmq worker
```

### Recuperação quando o broker está fora

O `POST /pedidos/` **não depende do broker estar no ar**: se a publicação falha,
o pedido fica gravado com `status = pendente_publicacao` e a API responde
**503** com o motivo. Medido:

| Passo | Resultado |
| ----- | --------- |
| `docker compose stop kafka` e `POST /pedidos/` | **HTTP 503**, `status = pendente_publicacao` no banco |
| `docker compose start kafka` | broker volta |
| `manage.py republicar_pedidos` | pedido 2796 publicado em `pedidos.criados` (offset 592) |
| worker consome | `status = processado`, `tentativas = 1` |

Ou seja, o broker indisponível custa um **503 honesto e recuperável**, não um
pedido fantasma.

> Nota: o throttle é irrelevante para quem não mede, então **não** se elevou
> `DRF_USER_RATE` no `docker-compose.yml` — a medição eleva por variável de
> ambiente, no mesmo comando do `up`, e o harness se recusa a publicar números
> contaminados por 429.


## Pagamento, notificação e o segundo fluxo Kafka (Aula 11)

O DoD da Aula 11 é um caminho de três passos: **criar pedido ➔ simular pagamento
➔ notificar**. O que a aula acrescenta não é o caminho — é que o pagamento é
**outro fluxo de eventos**, com tópico, grupo, offsets, retries e DLQ próprios.

```
POST /pedidos/            POST /pedidos/{id}/pagamento/     worker-pagamentos
      │                            │                                │
      ▼                            ▼                                ▼
pedidos.criados          pagamentos.registrados            UPDATE condicional
      │                            │                    (pagamento.status) +
      │                            │                    INSERT notificacao
      ▼                            │                                │
worker-kafka                           │                                │
      │                            │                                │
UPDATE pedido.status  ──► notificado_em preenchido ◄────────────────────┘
```

O `worker-kafka` continua tratando só de pedidos e o `worker-pagamentos` só de
pagamentos. Nenhum dos dois enxerga o tópico do outro.

### Por que dois fluxos e não dois tipos de evento no mesmo tópico

Poderia ser `pedidos.criados` com dois tipos de evento. Não é, e a razão é
operacional:

| Se fosse o mesmo tópico | O que acontece |
| ------------------------ | -------------- |
| Um consumidor só | processa pedido **e** pagamento; o worker de pagamento nunca roda |
| Dois consumidores | as partições são **disputadas**: cada worker lê metade dos eventos do outro fluxo, e metade dos pedidos não é processada por quem deveria |
| Uma DLQ só | "o que está preso?" exige inspecionar os dois fluxos para responder |

Com tópicos separados, cada fluxo tem consumidor, paralelismo
(`KAFKA_PARTICOES_PAGAMENTOS`), offset, dedupe e DLQ próprios — e o `--fluxo`
dos comandos de administração diz qual dos dois você está olhando.

O que os dois fluxos **compartilham** é a política de reentrega (`5,15,45 s`,
máximo 3) e o replayer. Estado, não é.

### Subir o ambiente

```powershell
# 1. sobe API + os dois workers + kafka, redis, db e inventory
docker compose up -d --build

# 2. cria a topologia dos DOIS fluxos (idempotente: pode repetir).
#    Precisa da API no ar: o comando roda dentro do container `api`.
docker compose exec api python api/manage.py declarar_topicos_kafka

# 3. confere que os dois fluxos estão de pé
curl.exe http://localhost:8000/health
```

```powershell
# estado do broker de um fluxo por vez
docker compose exec api python api/manage.py declarar_topicos_kafka --fluxo pagamentos --json
docker compose exec api python api/manage.py inspecionar_dlq_kafka --fluxo pagamentos
```

Os sete serviços do Compose: `api`, `inventory`, `worker-kafka`,
`worker-pagamentos`, `kafka`, `db` e `redis`. O RabbitMQ continua como profile
alternativo da Aula 9 e serve **apenas** ao fluxo de pedidos.

### A flag de falha injetada (leia antes de demonstrar a DLQ)

`PEDIDO_PERMITIR_SIMULACAO_FALHA` e `PAGAMENTO_PERMITIR_SIMULACAO_FALHA` estão
ligadas (`true`) por padrão no Compose, e as duas são consultadas **pela API**: a
view decide se aceita o header `X-Simular-Falha` e grava `simular_falha` no
registro. O worker não lê flag nenhuma: ele honra a marcação gravada no banco.

Com a flag desligada o header é **ignorado em silêncio** (o POST segue normal e
`simular_falha` fica `false`), que é o comportamento correto fora de
desenvolvimento: um cliente não deve poder sabotar o próprio pedido.

Os dois interruptores são separados porque a falha injetada leva a mensagem para
a **DLQ do seu fluxo**. Misturar as duas sabotagens no mesmo interruptor
tornaria "qual fluxo parou?" mais difícil de responder do que precisava.

### Endpoints novos

| Método | Rota | Quem | Devolve |
| ------ | ---- | ---- | ------- |
| `POST` | `/api/v1/pedidos/{id}/pagamento/` | dono do pedido | **201** com o pagamento em `registrado` e o bloco `evento` (tópico, partição, offset) |
| `GET` | `/api/v1/pedidos/{id}/pagamento/` | dono ou admin | o pagamento, com o desfecho que o **worker** gravou |
| `GET` | `/api/v1/notificacoes/` | dono (só as suas) ou admin (todas) | lista paginada, filtrável por `pedido` e `canal` |

Matriz de permissões da notificação:

| Verbo | Anônimo | user | admin |
| ----- | -------- | ---- | ----- |
| `GET /notificacoes/` | 401 | só as do próprio pedido | todas |

O corpo do `POST` decide o **método** e o **desfecho** do gateway simulado:
`metodo` (`pix`, `cartao_credito`, `boleto`), `aprovado`, `motivo_recusa`
(**obrigatório** quando `aprovado` é `false`, proibido quando é `true`) e
`canal` (`email`, `sms`, `push`; padrão `email`).

### O `status` do pagamento não muda na API

O `POST` responde `201` com `status: registrado` e o bloco `evento`. Esse
`registrado` é estado **local do produtor** — a linha foi criada e o evento foi
confirmado pelo broker. Quem vira `aprovado`/`recusado` é o worker, aplicando o
efeito do evento; é por isso que a transição é um `UPDATE` **condicional** no
worker, e não um `UPDATE` na API (que deixaria o `UPDATE` condicional sem linhas
para casar e a notificação nunca seria criada).

Então, logo depois do `POST`, um `GET` ainda devolve `registrado` — isso é o
funcionamento normal, não uma falha:

> **As barras invertidas no `-d` não são um erro de digitação.** No PowerShell
> 5.1, `-d '{"metodo": "pix"}'` chega na API como `{metodo: pix}` e a resposta é
> `JSON parse error`. As aspas duplas dentro de um argumento de executável nativo
> precisam ser escapadas (`\"`), como nos exemplos abaixo. Alternativas que não
> precisam de escape: `--%` (stop-parsing) ou `Invoke-RestMethod` com `-Body`.

```powershell
# 1. paga
curl.exe -X POST http://localhost:8000/api/v1/pedidos/5120/pagamento/ `
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" `
  -d '{\"metodo\": \"pix\", \"aprovado\": true, \"canal\": \"email\"}'
# {"status":"registrado", ..., "evento":{"topico":"pagamentos.registrados","fluxo":"pagamentos","chave":"5120","particao":1,"offset":1}}

# 2. alguns segundos depois, o worker aplicou o efeito
curl.exe http://localhost:8000/api/v1/pedidos/5120/pagamento/ -H "Authorization: Bearer $TOKEN"
# {"status":"aprovado", "aprovado":true, "notificado_em":"2026-...", ...}
```

Medido nesta aula (pedido 5120, `R$ 699.30`, PIX, canal email):

| Passo | Resultado |
| ----- | --------- |
| `POST /pedidos/` | `201`, `status=processado` (worker-kafka), total `699.30` |
| `POST /pedidos/5120/pagamento/` | `201`, `status=registrado`, `evento.chave=5120` (o **`pedido_id`**, não o `pagamento_id`) |
| ~7 s depois, `GET` do pagamento | `status=aprovado`, `notificado_em` preenchido |
| `GET /notificacoes/?pedido=5120` | `count: 1` — *"Seu pagamento de R$ 699.30 via PIX foi aprovado."* |

E o caminho da recusa (pedido 5121, `R$ 899.10`, cartão de crédito, SMS):
`status=recusado`, uma notificação, *"Seu pagamento de R$ 899.10 via cartão de
crédito foi recusado: saldo insuficiente"*, no canal `sms`.

### Re-POST: mesma tentativa republica, outra tentativa é 409

`Pagamento.pedido` é `OneToOne` — um pedido aceita **um** pagamento. O re-POST
bate no `IntegrityError` do banco, e quem decide o que responder é a
`idempotency_key` (SHA-256 de **pedido + método + desfecho**), não o
`IntegrityError`, que só diz que *já existe algum pagamento*:

| Re-POST | Resposta | Porquê |
| ------- | -------- | ------ |
| mesmo método, mesmo desfecho, ainda `registrado` | `200`, `republicado: true` | a cura do `503`: republica o evento perdido |
| mesmo método, mesmo desfecho, já resolvido | `200`, `republicado: false`, `evento.duplicado: true` | o gateway já respondeu; publicar de novo criaria uma **segunda** notificação para um fato já notificado |
| **método ou desfecho diferente** | **`409`** + `pagamento_existente` | é outra tentativa, e o `OneToOne` a impede |
| `aprovado: false` sem `motivo_recusa` | `400` | a coerência do desfecho é validada **na entrada** |

O `409` é o caso que dá sentido aos outros: sem comparar a chave, um `POST` com
`metodo: "boleto"` contra um pedido já pago com PIX devolvia `200` e o
pagamento em PIX — o cliente recebia um "deu certo" para um pedido que não
tentou fazer.

### Idempotência sob reentrega e replay

Três barreiras, nesta ordem: janela no **Redis** (`SET NX EX`), `UPDATE`
condicional no **PostgreSQL** e unicidade de `Notificacao.pagamento` (`OneToOne`).
A chave de dedupe é prefixada pelo nome do fluxo, então pagamento e pedido não
colidem.

Medido: cinco cópias do mesmo `PagamentoRegistrado` republicadas produziram
**uma** notificação. O Redis descartou as duplicatas; apagando a key do Redis à
mão, foi o `UPDATE` condicional que descartou — e a contagem continuou em 1, com
o pagamento inalterado.

### Falha injetada, escada e DLQ deste fluxo

```powershell
curl.exe -X POST http://localhost:8000/api/v1/pedidos/5124/pagamento/ `
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" `
  -H "X-Simular-Falha: 1" -d '{\"metodo\": \"pix\", \"aprovado\": true}'

# em outro terminal
docker compose logs -f worker-pagamentos
```

O header grava `simular_falha` no pagamento (**não** viaja no evento: o worker
lê do banco) e o consumidor levanta `FalhaInjetada`, uma exceção recuperável.
O que esperar:

| Momento | Banco | Log |
| ------- | ----- | ---- |
| t = 0 | `status=registrado`, `tentativas=1` | `PagamentoFalha`, `motivo: reentrega 1/3 em 5s` |
| t ≈ 6 s | `tentativas=2` | `PagamentoFalha`, `reentrega 2/3 em 15s` |
| t ≈ 22 s | `tentativas=3` | `PagamentoFalha`, `reentrega 3/3 em 45s` |
| t ≈ 67 s | `tentativas=4`, **sem notificação** | `PagamentoDlq` |

Os intervalos entre as mensagens medidos foram 6,7 s e 16,3 s para backoffs
declarados de 5 s e 15 s — a espera acontece **no tópico**, não num `sleep` do
worker.

Repare que **não existe** `status = falha` no `Pagamento`: o pedido continua
`processado`, e quem continua pendente é o **aviso**, que não foi criado.

Reprocessar a DLQ:

```powershell
# inspecionar sem consumir
docker compose exec api python api/manage.py inspecionar_dlq_kafka --fluxo pagamentos

# devolver ao tópico principal
docker compose exec api python api/manage.py inspecionar_dlq_kafka --fluxo pagamentos --reprocessar
```

O `--reprocessar` **descarta o `x-tentativa`** que veio da DLQ. Sem esse
reset, a mensagem volta com a escada já esgotada: o worker a processa uma vez e
a manda direto de volta para a DLQ, enquanto o comando reporta "1 mensagem
devolvida ao tópico principal". O sintoma — uma mensagem na DLQ que ninguém
colocou lá — não aponta para o header. O `x-motivo` também sai: ele descreve a
falha **daquela** tentativa.

> **"vazia" no `inspecionar` não significa "topico vazio".** As duas coisas
> medem coisas diferentes, e depois de um `--reprocessar` elas discordam de forma
> que parece bug:
>
> | Onde | O que mede | Situação depois de reprocessar as 4 mensagens |
> | ---- | ---------- | ------------------------------------------- |
> | `inspecionar_dlq_kafka` | o que o **grupo de inspeção** ainda não tratou (`synapseshop-dlq-inspecao-<fluxo>`) | `vazia` — o `--reprocessar` confirmou o offset, então não há o que ler |
> | `declarar_topicos_kafka --json` | o que o **tópico** ainda retém (`mensagens`) | `4` — o tópico é append-only |
>
> Reprocessar **devolve** a mensagem ao tópico principal; ela não sai da DLQ.
> Como a retenção da DLQ é de 30 dias, as 4 mensagens ficam lá até expirarem.

Medido: pedido 5115 com `X-Simular-Falha`, escada esgotada, `simular_falha`
limpo no banco e evento reprocessado — o worker aprovou, criou **uma**
notificação e a DLQ ficou vazia.

### Observabilidade dos dois fluxos

O `/health` devolve a **topologia completa** de cada fluxo em `fluxos` (tópico,
grupo, partições, retenção, tópico de DLQ, grupo de replay, a escada de
`topicos_retry` e `max_reentregas`):

```powershell
curl.exe http://localhost:8000/health
```

Agrupar por fluxo continua valendo, mas o detalhe não pode sumir: quem depura
pagamento precisa do estado do fluxo de pagamento, e o `/health` é a rota que
responde antes de qualquer outra quando algo trava.

O que o `/health` **não** traz é `lag`, offset confirmado e contagem de DLQ, e
isso é deliberado: o Compose o usa como `healthcheck` do container, então ler os
watermarks dos tópicos a cada sondagem transformaria o endpoint de liveness em
carga no broker. Para o estado que se move:

```powershell
# offsets, lag e tamanho da DLQ de um fluxo
docker compose exec api python api/manage.py declarar_topicos_kafka --fluxo pagamentos --json

# só a DLQ
docker compose exec api python api/manage.py inspecionar_dlq_kafka --fluxo pagamentos
```

Campos de log que só existem **por** haver dois fluxos: `fluxo` (qual stream a
linha veio — é o que permite filtrar `worker-kafka` e `worker-pagamentos` com o
mesmo `grep`) e `pagamento_id`. `pedido_id` sozinho não identifica a entidade:
um pagamento e um pedido de mesmo número coexistem. Os eventos de log do fluxo
ganham o prefixo `Pagamento` (`PagamentoProcessado`, `PagamentoDuplicado`,
`PagamentoFalha`, `PagamentoDlq`, `PagamentoPublicado`,
`PagamentoPublicacaoFalhou`); o laço de consumo é o mesmo dos dois fluxos.

### O que **não** foi feito (Anti-Hallucination)

A spec é explícita sobre não antecipar as aulas seguintes, e nada abaixo entrou:

* **nenhum** teste automatizado e **nenhuma** pipeline de CI/CD;
* **nenhum** dashboard ou extração de dados (o `Notificacao` foi modelado
  pensando nisso, mas é isso: uma tabela com índice, não um relatório);
* **nenhuma** IA, recomendação ou integração com serviço externo;
* o RabbitMQ **não** ganhou o segundo fluxo — implementá-lo exigiria uma
  topologia AMQP equivalente, e fingir que os dois brokers têm a mesma coisa
  seria mentir sobre a assimetria.

### Ficheiros da aula

* Contrato do evento: [`docs/contracts/pagamento_registrado.md`](docs/contracts/pagamento_registrado.md)
* Coleção Postman (21 requests, na ordem do DoD): [`collections/synapseshop_aula11.postman_collection.json`](collections/synapseshop_aula11.postman_collection.json)


## Testes automatizados e cobertura (Aula 12)

A suíte roda em `pytest`, num container descartável, cobrindo as **duas**
aplicações do repositório ao mesmo tempo — a API Django (`api/core`) e o
microsserviço FastAPI (`services/inventory/app`) — num único runner, com um
único `pyproject.toml` na raiz.

### Como executar

```bash
# A forma da equipe: profile `tests` do compose (imagem Dockerfile.tests).
docker compose --profile tests run --rm tests
```

O serviço `tests` espera o `db` ficar saudável (o pytest-django cria e
destrói um banco `test_*` por execução), monta o diretório de trabalho por
cima da imagem — editar um teste **não** exige rebuild; só mudou um
`requirements*.txt`? Aí é preciso `docker compose build tests`.

Equivalente local, com o banco publicado (`docker compose up -d db`):

```bash
pytest --cov          # relatório + gate de cobertura no stdout
```

O relatório HTML sai em `htmlcov/index.html` depois de qualquer execução com
`--cov`.

### Estrutura

```
tests/
├── conftest.py                 # fixtures globais + mocks (isolamento)
├── unit/
│   ├── test_cache_utils.py         # utils críticos do cache-aside
│   ├── test_contracts_pedido.py    # contrato do evento PedidoCriado
│   ├── test_contracts_pagamento.py # contrato do PagamentoRegistrado
│   ├── test_erros.py               # relatório de erro dos consumidores
│   ├── test_notificacoes.py        # título/mensagem por método e canal
│   ├── test_inventory_service.py   # regras de negócio do estoque
│   └── test_inventory_repository.py# repositório real (SQLite em memória)
└── integration/
    ├── test_catalog_lifecycle.py   # POST/GET + efeito na base (pedra do DoD 4)
    ├── test_pedidos_pagamento_fluxo.py # idempotência e eventos via HTTP
    ├── test_auth_throttling.py     # 429 do login com cota baixa
    └── test_inventory_endpoints.py # rotas FastAPI com repositório falso
```

### Convenções da equipe

* **Markers.** Todo teste nasce marcado: `@pytest.mark.unit` ou
  `@pytest.mark.integration`. Markers desconhecidos são erro
  (`--strict-markers`), então um marker novo precisa entrar em
  `pyproject.toml`.
* **Isolamento é estrutural, não de disciplina.** O `tests/conftest.py` é o
  ponto único de isolamento e o `api/config/settings_test.py` torna-o
  garantia: nenhum teste toca Redis, Kafka ou RabbitMQ. As fixtures
  `autouse` zeram cache e métricas entre testes e substituem o broker por um
  duplo em memória — um 429 ou um contador não podem vazar de um teste para
  o outro.
* **Relógio fixo.** Testes que comparam payload/timestamp usam a fixture
  `relogio_fixo` (freezegun, `tick=False`); nada de asserção dependente da
  hora em que rodou.
* **Inventory sem banco.** Os testes HTTP do estoque trocam
  `get_inventory_service` pelo serviço sobre o repositório falso do conftest;
  a tabela `inventory_items` (governada pelo Alembic) **não** é tocada pela
  suíte. O repositório real é coberto em
  `tests/unit/test_inventory_repository.py` contra um SQLite em memória.
* **Throttling.** As cotas sobem para 1000/min no settings_test para a suíte
  não estourar por acidente; o 429 é provado de propósito em
  `tests/integration/test_auth_throttling.py`, que devolve a taxa do `login`
  para 1/min.
* **Determinismo no tempo:** nada de `sleep` nem de asserção dependente da
  passagem de tempo real — onde o tempo importa, congela-se o relógio.
* **Suíte determinística:** sem I/O externo aberto e sem paralelismo; um
  teste injeta a própria semente/estado quando precisar.

### Metas de cobertura

* **85% global** nas duas aplicações, com *enforcement*: o gate
  `--cov-fail-under=85` no `pyproject.toml` reprova a execução abaixo disso.
* **100% nos utilitários críticos**: `cache_metrics` e o relatório de erros
  são cobertos por `tests/unit`; os contratos `PedidoCriado`/
  `PagamentoRegistrado` também têm unit tests dedicados (`test_contracts_*`),
  embora estejam fora da métrica por morarem na infra de mensageria.
* O restante pode equilibrar: a meta é global, não por arquivo; um regresso
  grande num só serviço derruba o gate, um pequeno ajuste de scaffold não é
  motivo para "esconder" arquivo.
* **Escopo medido**: o `--cov` cobre as duas aplicações. Ficam de fora as
  superfícies que a suíte não exercita por construção — `migrations`, `__init__`,
  `tests`, `management/commands`, `admin`/`apps` (bootstrap do Django) e
  `api/core/messaging/*` (infra de broker que só roda em worker/CLI:
  `consumir_pedidos`, `republicar_pedidos`, `declarar_topicos_kafka`). A
  justificativa de cada exclusão está no `omit` do
  `[tool.coverage.run]` no `pyproject.toml`.

### Pendências técnicas registadas

O DoD 7 pede as pendências e melhorias da aula como *issues* no
[repositório](https://github.com/Gilgamashed/AulaAI02/issues) — todas foram
criadas via API do GitHub. As corrigidas nesta aula ficaram **fechadas**, com
um comentário a apontar a correção e o teste que a cobre; a única aberta
continua em backlog:

**Corrigidas nesta aula (fechadas):**

* [#1](https://github.com/Gilgamashed/AulaAI02/issues/1) — indentação de
  `get_itens_recentes` no `ItemDetalheSerializer` (`api/core/serializers.py`),
  causa do 500 no `GET /items/{id}/detalhes/`;
* [#2](https://github.com/Gilgamashed/AulaAI02/issues/2) — a fixture `item` do
  `conftest.py` passava um campo `stock` inexistente no model;
* [#3](https://github.com/Gilgamashed/AulaAI02/issues/3) — `httpx` como
  dependência explícita da suíte (TestClient do FastAPI) no
  `requirements-dev.txt`;
* [#4](https://github.com/Gilgamashed/AulaAI02/issues/4) — publicação com
  `transaction.on_commit` adiada no `TestCase` devolveria 503 prematuro; os
  testes de fluxo usam `@pytest.mark.django_db(transaction=True)`;
* [#5](https://github.com/Gilgamashed/AulaAI02/issues/5) — os testes de
  throttling do login precisavam de `db` (o `simplejwt` consulta a tabela de
  usuários mesmo com credencial inválida);
* [#6](https://github.com/Gilgamashed/AulaAI02/issues/6) — o override da cota
  do login não surtia efeito via `override_settings`; o fixture
  `throttling_baixo` patcha o atributo de classe `ThrottleMemoriaScope`;
* [#7](https://github.com/Gilgamashed/AulaAI02/issues/7) — a PK `BIGINT` não
  autoincrementa no SQLite; `_item()` passa `id` explícito.

**Aberta:**

* [#8](https://github.com/Gilgamashed/AulaAI02/issues/8) — no host, o
  `pytest --cov` local precisa do `DATABASE_URL` com as credenciais do `.env`
  do compose para o pytest-django criar o banco `test_*` — a via oficial da
  equipe é o container (`docker compose --profile tests ...`).


## Checklist do Integrador Externo (Aula 13)

O que um terceiro precisa para consumir a API do SynapseShop. A fonte de
verdade do contrato é o ficheiro `docs/openapi.yaml` (OpenAPI 3.1), validado
por `scripts/lint-openapi.ps1` (Spectral, 0 erros/avisos).

### URLs de ambiente (dev)

| Ambiente | URL                                      | Documentação interativa        |
| -------- | ---------------------------------------- | ------------------------------ |
| API (DRF) | `http://localhost:8000`                 | `/docs/` (Swagger UI), `/redoc/` (ReDoc), `/docs/openapi.yaml` |
| Inventory (FastAPI) | `http://localhost:8001`        | `/docs` (nativo do FastAPI)    |

Verificação rápida: `GET /health` na API e no inventory devolvem
`{"status": "ok", ...}`.

### Autenticação (JWT)

- **Fluxo:** `POST /api/v1/auth/token/` com `{username, password}` →
  `{access, refresh}`. Use `Authorization: Bearer <access>` nas rotas
  protegidas. Renove com `POST /api/v1/auth/token/refresh/` e valide com
  `POST /api/v1/auth/token/verify/`.
- **Validade:** `access` expira em **5 min**, `refresh` em **1 dia**.
- **Credenciais demo (dev):** `demo_user` / `demo-user@Synapse2026` (papel
  `user`) e `demo_admin` / `demo-admin@Synapse2026` (papel `admin`), criadas por
  `manage.py seed_auth`; senhas configuráveis via `.env`
  (`SEED_ADMIN_PASSWORD`, `SEED_USER_PASSWORD`). Pessoais do Admin Django
  também via `.env`.
- **Matriz de permissões:** leitura de `/categories/` e `/items/` é pública;
  escrita exige `user`; rotas administrativas (categories/items PUT/PATCH/
  DELETE, `GET /cache/metrics/`) exigem `admin`. Anónimo a escrever = **401**;
  `user` em rota admin = **403**.
- **Notificações/pedidos:** usuários comuns acedem apenas aos próprios
  recursos (as listagens e detalhes já filtram por dono).

### Cabeçalhos obrigatórios

| Cabeçalho | Onde | Nota |
| --------- | ---- | ---- |
| `Authorization: Bearer <jwt>` | rotas protegidas | exigido na prática |
| `X-Trace-Id` (UUID) | rotas de negócio autenticadas | **contrato-alvo** documentado em `openapi.yaml`; a implementação atual ainda não o valida nem propaga |
| `Idempotency-Key` | `POST /pedidos/` | **contrato-alvo**; a implementação atual deriva a chave no servidor (re-POST do mesmo payload responde **200** com o mesmo `id`) |

### Limites de utilização (rate limits)

| Taxa | Aplica-se a | Convén |
| ---- | ----------- | ------ |
| `anon` — 20/min | requisições não autenticadas | 429 quando excedida |
| `user` — 100/min | usuários autenticados | 429 quando excedida |
| `login` — 5/min | `/auth/token/` e `/auth/token/refresh/` | 429 quando excedida |

As taxas são parametrizáveis por ambiente (`DRF_ANON_RATE`, `DRF_USER_RATE`).

### Paginação, filtros e ordenação

- **Paginação:** global `PageNumberPagination`, `PAGE_SIZE=20`, resposta
  `{count, next, previous, results}`; página inexistente = 404. O DRF usa
  `?page=`.
- **Contrato-alvo** (`openapi.yaml`): `?limit=` e `nextCursor` (cursor
  relativo ao DOD de aplicação), ainda não implementados.
- **Filtros:** `?category=`, `?is_active=`, `?min_price=`, `?max_price=` (itens);
  `?pedido=`, `?canal=email|sms`, `?status=`, `?search=` (notificações/pedidos).
- **Ordenação:** `?ordering=-price` (DRF); o contrato-alvo documenta
  `?sort=<campo>:<dir>` (ex.: `sort=enviadaEm:desc`).

### Erros padronizados

O contrato define o `ErrorSchema` seguindo a RFC 7807
(`application/problem+json`): `{type, title, status, detail, instance, code,
errors}`. `code` é um identificador estável para máquinas e `errors` mapeia a
validação por campo. Bastante: `400 Bad Request`, `401 Unauthorized`,
`403 Forbidden`, `404 Not Found`, `409 Conflict` (idempotência/OneToOne),
`503 Service Unavailable` (broker indisponível, pedido recuperável).

> A implementação atual devolve, em vários casos, o formato do DRF
> (`{"detail": ...}`). O `ErrorSchema` é o contrato-alvo; a migração é
> acompanhada no `docs/CHANGELOG.md`.

### Política de alterações de versão

- O contrato vive em `docs/openapi.yaml` e segue **SemVer**; cada aula é uma
  versão menor (`1.13.0` hoje).
- **Mudanças que quebram** (remoção/alteração de rota, campo ou cabeçalho)
  só entram numa versão maior ou menor com **aviso** no `docs/CHANGELOG.md` e
  deprecação quando razoável — não em patch.
- O prefixo `api/v1/` é **estável**: não muda sem nova versão de rota.
- Aula 13 não introduz dependências: o stack continua a subir com
  `docker compose up -d` como antes.

### Artefactos de consumo

- **Coleção Postman:** `collections/synapseshop_aula13.postman_collection.json`
  (41 requisições com exemplos de sucesso e erro, na ordem do fluxo pedido →
  pagamento → notificação).
- **Environment Postman:** `collections/synapseshop_aula13.postman_environment.json`
  (`base_url`, `inventory_url`, `token`, `trace_id`, `idempotency_key`).
- **Deploy/consumo em produção:** os URLs acima são de desenvolvimento. Para
  outros ambientes, troque as variáveis do environment (base URL, credenciais).

## Referências

- [Histórico de uso de IA generativa](PROMPTS.md)
- [Histórico de alterações](docs/CHANGELOG.md)
- [Diretriz SpecDD](specs/)