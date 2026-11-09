# Microsserviço de estoque com FastAPI (Aula 5)

> Conteúdo extraído do README.md (registro da aula). O README mantém apenas o resumo e o link para aqui.

## Microsserviço de estoque (Aula 5)

Microsserviço complementar de inventário em **FastAPI** (`services/inventory/`),
na porta **8001** (a 8000 é do Django). O domínio é o estoque real:
`sku`, `name`, `quantity` (disponível), `reserved` e `reorder_level`. Na Aula 5
a persistência era em memória; a partir da Aula 6 o estoque é persistido em
PostgreSQL com esquema governado pelo Alembic (ver seção da Aula 6).

> **Acesso no MVP (Aula 25 — complemento):** a porta 8001 é publicada apenas
> em `127.0.0.1` e o serviço direto continua sem autenticação. O caminho
> suportado para a apresentação é a página admin-only
> [`/app/inventario/`](../../README.md#inventário-fastapi-admin-only), que
> chama o proxy Django `/api/v1/inventario/`; o proxy valida o JWT/papel
> `admin` e só então encaminha para `/api/v1/inventory`. O navegador não fala
> com o FastAPI, portanto não há CORS.
>
> Para a demonstração, `seed_demo --com-inventario` cria/atualiza um item para
> cada produto ativo do catálogo com **10 a 30 unidades** determinísticas por
> SKU (`reserved=0`, `reorder_level=5`). O comando é idempotente e só chama o
> FastAPI quando a flag é usada; sem ela, o `seed_demo` continua sem rede.

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
# Acesso direto local-only, útil para depuração do microsserviço.
curl -X POST http://127.0.0.1:8001/api/v1/inventory \
  -H "Content-Type: application/json" \
  -d '{"sku": "APL-IP15-128", "name": "iPhone 15 128GB",
       "quantity": 10, "reserved": 0, "reorder_level": 5}'
```

Na UI da apresentação, use `demo_admin` em
`http://localhost:8000/app/inventario/`; o mesmo CRUD passa pelo proxy
`/api/v1/inventario/` e aparece nos logs do container `inventory`.

Qualidade do serviço validada com `ruff` e `mypy` (config em
`services/inventory/pyproject.toml`).

Coleção exportada para teste (importar no Postman e definir a variável
`base_url` como `http://localhost:8001`):
`collections/synapseshop_aula5.postman_collection.json`.

