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

### DoD da Aula 6

- [x] Modelagem relacional de User (Django auth) e InventoryItem (FastAPI).
- [x] Índices essenciais definidos (PK + índice único de SKU + backing indexes).
- [x] Índices essenciais de TODOS os modelos auditados e complementados (User/Item/Category/InventoryItem).
- [x] Regras de integridade relacional aplicadas (NOT NULL, UNIQUE, CHECK).
- [x] Migrações criadas e executadas com SQLAlchemy + Alembic no PostgreSQL.
- [x] Versionamento do schema implementado (`alembic_version` + revisões).
- [x] Rollback seguro demonstrado e validado.
- [x] Repositório transacional implementado (`InventoryRepository`).
- [x] Serviço consumindo o repositório (`InventoryService`).
- [x] Testes transacionais iniciais realizados (script de medição).
- [x] Tempos de execução coletados e registrados.
- [x] Decisões técnicas registradas neste README.
- [x] Não-antecipação respeitada (sem JWT/Redis/pytest/Order/Pedido).

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

### DoD da Aula 7

- [x] Autenticação JWT funcional com papéis `admin` e `user` (Groups).
- [x] Proteção das rotas administrativas (PUT/PATCH/DELETE exigem admin).
- [x] Throttling e segurança mínima configurados na API.
- [x] Endpoints críticos com paginação e filtros coerentes.
- [x] Coleção Postman com cenários de sucesso, erro e acesso negado.
- [x] Sem placeholders ansiosos nem funcionalidades de aulas futuras
      (sem Redis, mensageria, blacklist de tokens ou customização de
      `AUTH_USER_MODEL`).

## Referências

- [Histórico de uso de IA generativa](PROMPTS.md)
- [Diretriz SpecDD](specs/)