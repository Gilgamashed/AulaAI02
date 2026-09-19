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
| `db`         | `postgres:16-alpine` | Banco PostgreSQL (volume `pgdata` para persistência) |
| `inventory`  | build de `services/inventory/Dockerfile` | Microsserviço FastAPI de estoque: `/health`, `/docs` e CRUD em `/api/v1/inventory` (porta 8001) |

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
`sku`, `name`, `quantity` (disponível), `reserved` e `reorder_level`. Sem banco
nesta fase (persistência em memória; modelagem relacional é a Aula 6).

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

## Referências

- [Histórico de uso de IA generativa](PROMPTS.md)
- [Diretriz SpecDD](specs/)