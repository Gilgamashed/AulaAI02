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

Infraestrutura conteinerizada com Docker Compose (Aula 2/3). O ambiente é
composto por três serviços:

| Serviço      | Imagem             | Função                                               |
| ------------ | ------------------ | ---------------------------------------------------- |
| `api`        | build do Dockerfile | API Django REST Framework: `/health` + rotas CRUD em `/api/v1/` (porta 8000) |
| `db`         | `postgres:16-alpine` | Banco PostgreSQL (volume `pgdata` para persistência); porta interna `db:5432` **publicada em `localhost:5432`** para permitir comandos de gerenciamento locais (venv) |
| `inventory`  | build de `services/inventory/Dockerfile` | Microsserviço FastAPI de estoque: `/health`, `/docs` e CRUD em `/api/v1/inventory` (porta 8001); persistência própria no PostgreSQL governada pelo Alembic (Aula 6) |

O `Dockerfile` usa **multistage build** (`builder` prepara as dependências;
`runtime` copia apenas o necessário) com cache eficiente de dependências e
execução via usuário não-root `appuser`. O serviço `api` só inicia depois que
o banco responde com sucesso ao `healthcheck` (`depends_on` +
`service_healthy`).

### Pré-requisitos

- Docker Desktop (com WSL2) e Docker Compose.
- Arquivo `.env` na raiz com as credenciais do banco (usar `.env.example`
  como referência). O Compose o carrega automaticamente.

### Subir o ambiente

```bash
docker compose up -d --build
```

### Validar a disponibilidade

```bash
curl http://localhost:8000/health
# {"status": "ok", "service": "synapseshop-api"}
curl http://localhost:8001/health
# {"status": "ok", "service": "synapseshop-inventory"}
```

### Acompanhar os logs

```bash
docker compose logs -f api          # logs do serviço API
docker compose logs -f db           # logs do PostgreSQL (ex.: "database system is ready")
docker compose logs -f inventory    # logs do microsserviço de estoque
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


## Mensageria assíncrona com RabbitMQ (Aula 9)

A Aula 9 introduz o **processamento assíncrono por eventos** para o fluxo de
pedidos. A API deixa de esperar o processamento terminar: cria o pedido,
publica o evento `PedidoCriado` com publisher confirms e responde **201**. Um
**worker** independente consome a fila e avança o estado para `processado` (ou
`falha`), com **idempotência ponta a ponta** e **DLQ** para falhas
irrecuperáveis.

### Ambiente: serviços `rabbitmq` e `worker`

O `docker-compose.yml` adiciona dois serviços:

| Serviço      | Imagem                     | Função                                                    |
| ------------ | -------------------------- | --------------------------------------------------------- |
| `rabbitmq`    | `rabbitmq:3.13-management-alpine` | Broker AMQP 0-9-1, com a UI de gestão em `http://localhost:15672` (usuário/senha via `.env`). Filas duráveis, exchanges declarados no startup. |
| `worker`      | build do Dockerfile       | Consumidor assíncrono via `python api/manage.py consumir_pedidos`. Roda no mesmo código Django (mesmos models e migrações), sem duplicar ORM. Sobe após `api` e `rabbitmq` saudáveis. |

O volume `rabbitmqdata` mantém as mensagens persistentes se o container reiniciar.

O serviço `worker` **não** tem `container_name` de propósito: é o que permite
`docker compose up -d --scale worker=3` (um `container_name` fixo impede
escalar, porque o segundo container não teria nome livre).

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

### Observabilidade da Aula 9

- **Logs JSON** (logger `core.messaging`): `WorkerIniciado`, `MensagemRecebida`, `PedidoDuplicado`, `PedidoProcessado`, `PedidoFalha`, `PedidoDlq`, `PedidoPublicado`, `PedidoPublicacaoFalhou`, com `evento_id`, `pedido_id`, `chave_idempotencia`, `tentativa`, `atraso_fila_ms`, `duracao_ms`.
- **Métricas em memória** (`core.messaging.metricas`): `recebidas`, `processadas`, `duplicadas`, `falhas`, `reentregas`, `dlq`, `invalidas`.
- **Medição ponta a ponta**: `scripts/measure_messaging.py` (stdlib) faz POST autenticado com `Idempotency-Key` explícita, aguarda `processado` por polling com intervalo adaptativo e reporta: latência **POST** (publisher confirm) e **publicação→processado** (baseada em `evento.publicado_em`), idempotência (3 reenvios), escada de reentrega com timestamps por tentativa, e profundidade das filas via Management API (`:15672`). Usa sessão JWT com renovação automática e pode `--purgar` as filas antes da medição.

**Medições reais (execução local, 20 pedidos + idempotência + DLQ):**

| Métrica | n | média | p50 | p95 | máx |
|---|---|---|---|---|---|
| POST (publisher confirm) | 20 | 78,83 ms | — | 101,76 ms | 105,45 ms |
| publicação → processado | 20 | 82,35 ms | 75 ms | 124 ms | 172 ms |

**Idempotência:** 3 reenvios com a mesma `Idempotency-Key` → **HTTP 200**, mesmo `pedido_id`, `evento.duplicado = true` (idempotente).

**Escada de reentrega (X-Simular-Falha):** tentativas registradas em `t+0,0s` (tentativa 0→1), `t+6,1s` (1→2), `t+21,3s` (2→3), `t+66,8s` (3→DLQ) — correspondendo aos degraus **5 s / 15 s / 45 s**. Pedido terminou em `status=falha`, mensagem na `pedidos.criados.dlq`. Após a leitura, as filas ficaram: `pedidos.criados.dlq` com 1 mensagem pronta (evidência da DLQ) e as demais vazias.


## Vazão, múltiplos consumidores e trade-offs (Aula 10)

A Aula 9 provou que o fluxo funciona e mediu **latência**. A Aula 10 mede o que
faltava: **quanto o pipeline aguenta** e **o que acontece quando se troca
disponibilidade por latência**.

### Desvio consciente: por que RabbitMQ e não Kafka

A spec da Aula 10 pede Apache Kafka. A implementação segue em **RabbitMQ**, e o
motivo é o mesmo que validou a Aula 9: a topologia necessária aqui é
*filas com TTL e dead-letter*, não *log distribuído com retenção*. As
equivalências são diretas:

| Item pedido (Kafka)                        | O que foi implementado (AMQP 0-9-1)                                       |
| ------------------------------------------ | -------------------------------------------------------------------------- |
| Tópico e partições                         | Exchange `topic` + filas nomeadas (`pedidos.criados`)                     |
| Retenção/expurgo por tempo                 | `x-message-ttl` nas filas de retry (5/15/45 s)                             |
| Consumidor com `ack` manual                | `auto_ack=False` + `basic_ack` **depois** do efeito                        |
| `acks=all` / publisher confirm             | `confirm_delivery()` + `mandatory=True`                                    |
| Consumer group (partição por consumidor)   | round-robin entre consumers da **mesma** fila                              |
| Dead letter                                | DLX + fila terminal `pedidos.criados.dlq`                                  |
| Backoff escalonado                         | escada de filas de retry com TTL, uma por degrau                           |

O que **não** foi fingido: em Kafka o paralelismo de consumo viria de partições
(várias partições = várias instâncias do mesmo grupo), enquanto aqui ele vem de
vários consumers na mesma fila. A diferença é que Kafka reordena por chave
dentro da partição e o RabbitMQ não tem noção de partição — mas para um fluxo
de **um pedido por mensagem**, os dois modelos entregam a mesma propriedade
que importa aqui: *N consumidores, cada mensagem para exatamente um deles*.

### Como as medições foram feitas

```powershell
# com 1 consumidor
docker compose up -d
.venv\Scripts\python.exe scripts\measure_messaging.py --purgar --pedidos 20 `
    --duplicatas 3 --forcar-falha 1 --carga 60 --concorrencia 8 --inspecionar-dlq

# com 3 consumidores concorrentes
docker compose up -d --scale worker=3
.venv\Scripts\python.exe scripts\measure_messaging.py --purgar --pedidos 20 `
    --duplicatas 3 --forcar-falha 1 --carga 60 --concorrencia 8 --inspecionar-dlq

# resumo do log transacional (não precisa da API no ar)
docker compose logs --no-color worker > logs_worker.jsonl
.venv\Scripts\python.exe scripts\measure_messaging.py --analisar-logs logs_worker.jsonl
```

Duas regras metodológicas que mudam o número final:

- **`DRF_USER_RATE` precisa estar no mesmo comando do `docker compose up`.**
  O `docker-compose.yml` injeta `${DRF_USER_RATE:-100/min}`; sem a variável no
  ambiente, qualquer `up` posterior recria a API no padrão. Ver "Defeitos de
  medição encontrados".
- **A latência é medida por *polling*** (`GET /pedidos/{id}`), com intervalo
  de 0,2 s no primeiro ciclo. Em fluxo feliz a latência é da ordem de dezenas de
  milissegundos, ou seja, do mesmo tamanho do intervalo — o número honesto é
  "dezenas de ms", não o valor exato.
- **As duas execuções têm que ser encostadas.** As tabelas abaixo vêm de duas
  rodadas seguidas, com 1 e com 3 consumidores, na mesma sessão. Ver
  "Por que os números foram medidos de novo, em pares".

### Latência e vazão, com 1 e com 3 consumidores

| Cenário (n = 60, 8 POSTs em paralelo) | 1 consumidor | 3 consumidores |
| ------------------------------------ | ----------- | -------------- |
| Publicação (POST → broker confirma)   | 11,46 ped/s | 10,72 ped/s    |
| Processamento (ponta a ponta)        | 7,23 ped/s  | 7,13 ped/s     |
| Latência sob carga — média           | 4.549 ms    | 4.720 ms       |
| Latência sob carga — p50 / p95       | 4.828 / 5.183 ms | 5.072 / 5.566 ms |
| Latência em repouso (n = 20) — média | 85,9 ms     | 114,8 ms       |
| POST em repouso — média              | 92,3 ms     | 118,7 ms       |
| Consumers na fila                    | 1           | 3              |

Fluxo feliz (n = 20): com 1 consumidor, média **85,9 ms** (p50 80 ms, p95 112 ms);
com 3, média **114,8 ms** (p50 106 ms, p95 178 ms).

**O consumidor extra não melhora nada — ele piora um pouco.** Com 3 consumidores
a vazão cai de 7,23 para 7,13 ped/s e a latência em repouso sobe de 85,9 para
114,8 ms. Em repouso a fila está sempre vazia: o pedido é publicado e consumido
em milissegundos, e colocar mais dois containers nesse caminho só acrescenta
concorrência de conexão e alguma contenção no banco. Sob carga, a latência vai
de ~86 ms para ~4,6 s **com 1 ou com 3 consumidores** — o número de POSTs
concluídos por segundo é o mesmo.

### Por que os números foram medidos de novo, em pares

A primeira rodada desta aula rodou 1 consumidor numa sessão e 3 consumidores em
outra. Repetir a medição mostrou que **isso não é comparável**: o mesmo código,
no mesmo host, rendia 9,29 ped/s com 1 consumidor numa sessão e 7,23 ped/s
noutra — uma variação de ~22% que não tem nada a ver com a mudança de
arquitetura. Somada à variação de latência (~38%), uma comparação entre
sessões diferentes teria uma história verosímil e falsa: "3 consumidores deram
+20% de vazão".

Por isso os números da tabela acima vêm de **duas execuções encostadas no mesmo
minuto, na mesma máquina, com o mesmo tamanho de banco**, e ambas passaram pelo
contador de 429 (`respostas_429: 0`, `invalido: false`). A lição fica
registrada de propósito: em benchmark, comparar execuções separadas é o erro
mais fácil de cometer e o mais difícil de perceber, porque a tabela continua
bonita.

### Múltiplos consumidores: a distribuição é que prova

Com 3 consumers na mesma fila, a fase de carga (60 mensagens) foi dividida
exatamente em três:

```json
"processados_por_worker": {"worker-1": 20, "worker-3": 20, "worker-2": 20}
```

20 + 20 + 20 = 60. Nenhuma mensagem processada duas vezes, nenhuma perdida: o
RabbitMQ entrega cada mensagem a **um** consumer (`basic_consume` compete entre
eles), e o round-robin fica evidente no log. É a propriedade que a
partição-por-consumidor do Kafka dá, aqui sem precisar de partições.

### Onde está o gargalo (e por que 3 consumidores não ajudaram)

O consumo tem folga de sobra. Do log transacional da fase de carga, com 3
consumidores (60 mensagens):

| Métrica do log                       | média   | p50    | p95    |
| ------------------------------------ | ------- | ------ | ------ |
| `duracao_ms` (trabalho no consumidor) | 12,9 ms | 10,9 ms | 27,6 ms |
| `atraso_fila_ms` (espera na fila)     | 23,6 ms | 20 ms   | 29 ms   |

Ou seja: **cada mensagem consome ~13 ms de trabalho e espera ~24 ms na fila**.
Um consumer sozinho teria capacidade de ~1/0,013 s ≈ **77 mensagens/s**, e os
3 juntos dariam ~230/s — muito acima dos ~7/s medidos. A fila nunca chega a
acumular (`atraso_fila_ms` p95 = 29 ms), então os consumidores não estão
saturados.

> O `n` do `atraso_fila_ms` no relatório do `--analisar-logs` é 120 para 60
> mensagens: o campo aparece em duas linhas de log por mensagem
> (`MensagemRecebida` e `PedidoProcessado`) e o analisador agrega as duas. O
> valor por mensagem é o mesmo, então os percentis não mudam.

O limite está **antes**, na publicação. Do log da API (as duas rodadas
pareadas):

| Métrica da API                            | valor        |
| ----------------------------------------- | ------------ |
| `PedidoPublicado.duracao_ms`               | p50 **29,8 ms** (p95 70,4 ms) |
| `TopologiaDeclarada` por publicação        | **1 para 1** (164 publicações = 164 declarações) |

Cada `POST /pedidos/` **abre uma conexão AMQP nova e redeclara a topologia
inteira** (3 exchanges + 5 filas) antes de publicar. O cliente único da
medição (8 threads, `urllib` bloqueante) satura em ~11 POSTs/s, e é esse o
teto do experimento:

| Concorrência do cliente | POSTs/s | latência média do POST |
| ----------------------- | ------- | ---------------------- |
| 8                       | 10,7    | 707 ms                 |
| 24                      | 10,0    | 1.849 ms               |

Triplicar a concorrência **não** aumentou a vazão e apenas empurrou a latência
do POST para cima — a assinatura clássica de um recurso saturado mais acima.
Conclusão honesta: **o gargalo desta arquitetura é o produtor, não o
consumidor.** A correção é o equivalente AMQP do *producer pooling* que a spec
pede para o Kafka: uma conexão/canal compartilhado por processo, topologia
declarada uma vez no startup, `confirm_delivery` já ligado. Isso é trabalho de
uma aula seguinte — aqui fica medido e diagnosticado, não "adicionado e
comemorado".

### Idempotência × latência × throughput

Os três requisitos puxam em direções opostas, e o desenho escolhe posição:

| Decisão                                | Ganho                                        | Custo                                        |
| -------------------------------------- | -------------------------------------------- | -------------------------------------------- |
| Dedupe no Redis antes do efeito        | evita transação e `UPDATE` no banco         | 1 ida e volta ao Redis por mensagem (~1 ms)  |
| Dedupe **só** no banco (`UPDATE` cond.)| dispensa o Redis no caminho crítico          | transação no banco para toda mensagem         |
| Backoff 5/15/45 s em filas             | não trava a fila com retentativa             | falha terminal demora ~65 s para ser visível |
| `prefetch_count=1`                     | processamento por mensagem isolado           | 1 consumer só processa 1 por vez             |
| Confirmação do produtor                | nenhum 201 "fantasma"                        | POST espera o disco do broker (~30 ms)        |

O que a medição mostra é que **a idempotência é barata** (uma ida e volta ao
Redis, ~1 ms de um total de ~13 ms de trabalho no consumidor) e que **o custo
real da consistência está em esperar o resultado durável antes de responder
201** — se a API respondesse antes do confirm, o POST cairia de ~30 ms (p50 do
`PedidoPublicado.duracao_ms`) para ~1 ms e o cliente passaria a correr o risco
de um pedido que nunca existiu.

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

### At-least-once: worker morto no meio

Teste de caos: uma carga em andamento e os **3 containers `worker` levados com
`SIGKILL`** (`docker compose kill worker`), sem chance de requeue orderly, e
depois religados:

| Execução            | Publicados | Processados | Não processados | DLQ | Filas no fim |
| ------------------- | ---------- | ----------- | --------------- | --- | ------------ |
| 60 pedidos, conc. 8 | 60         | 60          | 0               | 0   | todas vazias |

**Nenhuma mensagem perdida.** É a propriedade que importa no ack manual: a
confirmação é enviada **depois** do efeito (`dedupe.confirmar()` e só então
`basic_ack()`), então uma queda de conexão entrega a mensagem de novo em vez de
fingir que ela sumiu. O reprocessamento é seguro porque as duas barreiras de
idempotência descritas acima.

O que **não** foi reproduzido: uma duplicata de verdade. A janela entre
"efeito confirmado no banco" e "`basic_ack`" é de sub-milissegundo, então o
SIGKILL raramente cai dentro dela — nos testes o `SIGKILL` pegou a fila já
drenada. Para provar a duplicata de forma determinística seria preciso um ponto
de injeção de falha (algo como `X-Simular-Quase-ack`, que derruba o processo
entre o commit e o ack). O que se pode afirmar com a evidência coletada é a
ausência de perda; o caminho de duplicata está implementado e logado
(`PedidoDuplicado`), mas sua reprodução exige essa flag.

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
`duracao_ms`/`atraso_fila_ms` e trabalho por instância (é o que produz o
20/20/20 acima). O pacote de mensageria emite **21 tipos de evento**, e a lista
foi conferida contra o código (não é contagem de memória):

| Grupo                | Eventos                                                                                          |
| -------------------- | ------------------------------------------------------------------------------------------------ |
| Ciclo da mensagem    | `MensagemRecebida`, `MensagemEncerrada`, `PedidoProcessado`, `PedidoDuplicado`, `PedidoFalha`, `PedidoDlq` |
| Publicação           | `PedidoPublicado`, `PedidoPublicacaoFalhou`, `TopologiaDeclarada`                                   |
| Falha de política    | `ReentregaFalhou`, `DlqFalhou`, `PoliticaInconsistente`                                            |
| Dedupe               | `DedupeDegradado`, `DedupeNaoConfirmado`, `DedupeNaoLiberado`                                       |
| Ciclo de vida worker | `WorkerIniciado`, `WorkerEncerrado`, `WorkerInterrompido`, `WorkerLimiteAtingido`, `WorkerParando`, `WorkerSemConexao` |

`PedidoCriado` **não** aparece nessa lista: é o nome do contrato
(`contracts.EVENTO_PEDIDO_CRIADO`), não um evento de log — o evento de
publicação que o produtor emite é `PedidoPublicado`.

### Defeitos de medição encontrados (e corrigidos)

Os três maiores problemas desta aula não foram no sistema de mensageria — foram
**no próprio instrumento de medição**, e vale registrá-los porque é o que
transforma um relatório em evidência:

1. **A API grava `falha` antes de publicar na DLQ.** A medição original usava
   `sleep(2)` entre "API disse `falha`" e "ler as filas". Capturado com
   snapshots finos, o instante do `falha` é `t+68,1s` com `DLQ=0, retry.3=1` — a
   mensagem ainda estava na última fila de retry. Com o sleep, o relatório ora
   diria `dlq=0`, ora `dlq=1`. **Corrigido**: `aguardar_mensagem_na_dlq()`
   pergunta ao broker até a mensagem aparecer, e reporta quanto esperou
   (1,04 s e 1,55 s nas rodadas pareadas de 3 e 1 consumidor).
2. **Throttling absorvido em silêncio.** O `docker compose up --scale worker=3`
   recriou a API com `DRF_USER_RATE` no padrão (100/min) porque a variável não
   existia naquele shell. 11 respostas 429 (18 s de espera cada) empurraram a
   latência média da carga para **53 s**, contra ~4,5 s na rodada limpa — e o
   relatório saía limpo e bonito. **Corrigido**: todo 429 é contado, e a
   execução sai com código 1 e um aviso se passar de `--tolerar-429` (padrão 0).
3. **`RemoteDisconnected` não é `URLError`.** Derrubar a API no meio da carga
   (o próprio teste de caos) matava o harness com traceback. **Corrigido**:
   `OSError`/`http.client.HTTPException` entram na mesma fila de retentativa,
   em contador separado do 429 (indisponibilidade é esperada no teste de caos e
   não invalida a medição).
4. **Comparar execuções de sessões diferentes.** Detalhado em "Por que os
   números foram medidos de novo, em pares": o mesmo código rendeu 9,29 e 7,23
   ped/s em duas rodadas de 1 consumidor, e a comparação entre sessões teria
   inventado um ganho de vazão com 3 consumidores que não existe. **Corrigido**:
   as duas colunas da tabela vêm de rodadas encostadas, e ambas reportam
   `respostas_429: 0`.

### Comandos úteis (Aulas 9 e 10)

```powershell
# Verificar topologia e logs do worker
docker compose logs -f worker

# Escalar consumidores (o service não tem container_name de propósito)
docker compose up -d --scale worker=3

# Recuperar pedidos em pendente_publicacao
docker compose exec api python api/manage.py republicar_pedidos --dry-run
docker compose exec api python api/manage.py republicar_pedidos

# Medição completa (latência, idempotência, vazão, DLQ, consumidores)
.venv\Scripts\python.exe scripts\measure_messaging.py --purgar --pedidos 20 `
    --duplicatas 3 --forcar-falha 1 --carga 60 --concorrencia 8 --inspecionar-dlq

# Só a vazão, sem esperar a escada de reentrega (~65 s)
.venv\Scripts\python.exe scripts\measure_messaging.py --purgar --pedidos 0 `
    --duplicatas 0 --forcar-falha 0 --carga 60 --concorrencia 8

# Resumo do log transacional
docker compose logs --no-color worker > logs_worker.jsonl
.venv\Scripts\python.exe scripts\measure_messaging.py --analisar-logs logs_worker.jsonl

# Dedupe degradado (fail-open)
docker compose stop redis
.venv\Scripts\python.exe scripts\measure_messaging.py --purgar --pedidos 10 --duplicatas 3
docker compose start redis
```

> Nota: o throttle é irrelevante para quem não mede, então **não** se elevou
> `DRF_USER_RATE` no `docker-compose.yml` — a medição eleva por variável de
> ambiente, no mesmo comando do `up`, e o harness se recusa a publicar números
> contaminados por 429.


## Referências

- [Histórico de uso de IA generativa](PROMPTS.md)
- [Diretriz SpecDD](specs/)