# Checklist do Integrador Externo (Aula 13)

> Conteúdo extraído do README.md (registro da aula). O README mantém apenas o resumo e o link para aqui.

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

> Passo a passo completo de login e gestão de usuários:
> [`docs/autenticacao.md`](autenticacao.md).

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

