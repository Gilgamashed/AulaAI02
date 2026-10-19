# Modelagem relacional, índices e migrações (Aula 6)

> Conteúdo extraído do README.md (registro da aula). O README mantém apenas o resumo e o link para aqui.

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


