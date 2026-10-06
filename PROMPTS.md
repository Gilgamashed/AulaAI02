# PROMPTS.md

Registro do histórico de uso de IA generativa no projeto SynapseShop.

## Como registrar

Ao usar qualquer ferramenta de IA (assistentes, código, documentação, revisão),
adicione uma entrada com o formato abaixo em ordem cronológica.

```markdown
## [AAAA-MM-DD] Título resumido

- **Ferramenta:** <nome da ferramenta/modelo>
- **Contexto:** <qual spec/tarefa da aula motivou o uso>
- **Prompt:** <o que foi solicitado>
- **Resultado/Decisão:** <o que foi gerado/adotado, ou por que foi rejeitado>
- **Revisão humana:** <o que o time validou/ajustou>
```

Histórico de uso de IA da equipe — complete conforme a metodologia SpecDD for
executada (registrar apenas usos reais durante o desenvolvimento).

## [2026-09-18] Aula 5 — PROMPTS-TEMPLATE.md e prompts do inventory (itens 2 + 6)

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 5 — alinhamento dos itens 2 (elaborar prompts que
  descrevam explicitamente modelos Pydantic, dependências e respostas padrão) e
  6 (criar e versionar `PROMPTS-TEMPLATE.md` para padronizar descrição de
  requisitos, restrições e formatos de saída ao acionar ferramentas de IA).
- **Prompt:** "vamos replanejar tudo. Nesta etapa, vamos alinhar o item 2 com o
  item 6. Vamos elaborar os prompts que descrevam os modelos Pydantic,
  dependências e respostas padrão e vamos criar e versionar o
  PROMPTS-TEMPLATE.md." Decisões alinhadas via perguntas: exemplo preenchido
  dentro do próprio template; prompts descrevendo o domínio real (SKU + 
  quantity/reserved/reorder_level e CRUD completo); matriz de status com **400**
  para payload inválido (padronizando com o IA-SAFE).
- **Resultado/Decisão:** criado `PROMPTS-TEMPLATE.md` na raiz, com duas partes:
  **Parte A** — template genérico reutilizável (Contexto → Objetivo → Requisitos
  técnicos → Modelos Pydantic → Dependências → Respostas padrão e matriz de
  status → Restrições SpecDD → Formato de saída → Critérios de aceite) com link
  ao IA-SAFE.md; **Parte B** — exemplo preenchido do microsserviço inventory
  (Aula 5), descrevendo o domínio real (pattern de SKU `XXXX-AAAA-BBBB`,
  `quantity`/`reserved`/`reorder_level` com `ge=0`), a dependência `ServiceInfo`
  via `Depends`, o envelope `ApiResponse[T]` com `ok()`/`error()` e a matriz de
  status (200/201/204/400/404/409).
- **Revisão humana/ajuste manual:** decisão de padronizar **400** (e não 422)
  para payload inválido exige handler customizado de `RequestValidationError`
  no FastAPI — registrado como pendente do item 4 nos critérios de aceite do
  template. Template versionado na raiz; uso registrado neste módulo.

## [2026-09-18] Aula 5 — Coleção Postman do microsserviço inventory

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Aula 5 — gerar a coleção de testes das rotas do microsserviço de
  estoque, espelhando o padrão da coleção da Aula 4.
- **Prompt:** "podemos fazer uma collections com as novas rotas da aula 5?"
  Decisões alinhadas: manter endpoints de documentação (`/docs`, `/openapi.json`)
  **fora** da coleção (mesmo padrão da Aula 4) e registrar a referência no
  README e o uso no PROMPTS.
- **Resultado/Decisão:** criada `collections/synapseshop_aula5.postman_collection.json`
  (Postman v2.1.0, `base_url=http://localhost:8001`, UUID próprio) com pastas
  **Core** (`GET /` e `GET /health`) e **Inventory** (CRUD completo em
  `/api/v1/inventory`): GET list 200, POST criar 201, duplicado 409, SKU inválido
  400, quantity negativa 400, GET por SKU 200, inexistente 404, path malformado
  400, PATCH parcial 200, PATCH vazio 400, DELETE 204 e GET pós-exclusão 404.
  README atualizado (seção do inventory) com a referência à coleção.
- **Revisão humana/ajuste manual:** JSON validado (`ConvertFrom-Json`); nomes e
  descrições em PT-BR com o status esperado em cada request. Pendente commit/push.

## [2026-09-18] Aula 5 — Rotas mínimas, handlers 400 e integração ao compose (itens 3, 4 e 5)

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 5 — executar os itens 3 (metodologia/qualidade
  com tipagem validada via ruff/mypy), 4 (rotas mínimas e respostas padrão com
  domínio real) e 5 (integração do inventory ao `docker-compose.yml`).
- **Prompt:** "Qualquer refinamento que a gente venha a fazer... precisa ser
  enxuto, direto ao ponto, senão não serve. Vamos executar os itens 3, 4 e 5 da
  Aula 5." (execução após alinhamento prévio: CRUD completo, domínio real
  SKU + quantity/reserved/reorder_level, **400** para payload inválido).
- **Resultado/Decisão:**
  - Item 3: `services/inventory/pyproject.toml` versionado (ruff: `line-length
    100`, `py312`, selects `E/F/W/I/UP`; mypy: `disallow_untyped_defs`); ruff e
    mypy passando em `app/` (corrigidos E501, W292 e UP046/UP047 — `ApiResponse`
    migrado para type parameters PEP 695).
  - Item 4: `app/handlers.py` com handler customizado de
    `RequestValidationError` → **400** no envelope (padronização da squad) e de
    `HTTPException` → status original no envelope; `app/schemas.py` reescrito no
    domínio real (`SKU_PATTERN = ^[A-Z]{2,4}-[A-Z0-9-]+$` alinhado à Aula 4,
    `InventoryItemCreate/Update/Item`); `app/routers/inventory.py` com CRUD
    completo sob `/api/v1/inventory` (SKU do path validado com
    `Path(pattern=...)`, PATCH com `exclude_unset` + 400 se payload vazio).
  - Item 5: serviço `inventory` adicionado ao `docker-compose.yml` (build de
    `./services/inventory`, porta `8001:8001`, healthcheck `urllib` em
    `/health`, sem `depends_on` do `db` — sem banco nesta fase).
  - Template: pattern de SKU da Parte B do `PROMPTS-TEMPLATE.md` corrigido para
    o padrão real da Aula 4.
- **Revisão humana/ajuste manual:** verificação do compose `config` pegou a
  chave `inventory` fora do bloco `services:` (indentação) — corrigido e
  revalidado. Validação no stack (`docker compose up -d --build`): matriz do
  DoD no 8001 OK (GET 200, POST 201, duplicado 409, SKU inválido 400, quantity
  negativa 400, GET 200, SKU de path inválido 400, SKU inexistente 404, PATCH
  200, PATCH vazio 400, DELETE 204, GET pós-delete 404, `/docs` e
  `/openapi.json` 200) e regressão do Django `/health` 200 na 8000; os três
  serviços healthy. Nota: no `curl` do PowerShell 5.1 o JSON continua via
  `--data-binary @arquivo` (padrão já registrado).

## [2026-09-18] Aula 5 — Scaffold do microsserviço inventory em FastAPI

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 5, item 1 de "Tarefas e Responsabilidades" — criar
  o esqueleto (scaffold) do microsserviço complementar de estoque em FastAPI.
- **Prompt:** "Estou começando uma nova aula, vamos seguir a
  specs/specs_da_aula_5.md. Vamos começar seguindo apenas o primeiro item do
  Tarefas e Responsabilidades — Criar o esqueleto do microsserviço FastAPI.
  Sempre que for oportuno, faça comentários a respeito do que está sendo feito."
  Decisões alinhadas via perguntas: diretório dentro de `services/`, Dockerfile
  próprio já criado (integração ao compose só no item 5) e campos Pydantic
  mínimos de exemplo (domínio real alinhado no item 4).
- **Resultado/Decisão:** criado `services/inventory/` com `app/main.py`
  (FastAPI app com `/docs`, `/openapi.json`, `/health`, `/` com dependência
  injetada), `app/schemas.py` (modelos Pydantic de exemplo com validação:
  `sku` não-vazio, `quantity >= 0`), `app/responses.py` (envelope padrão
  `ApiResponse[T]` com factories `ok()`/`error()`), `app/dependencies.py`
  (`ServiceInfo` via `Depends`), `app/routers/inventory.py` (rotas de exemplo
  CRUD tipadas sob `/api/v1/inventory`), `requirements.txt` (fastapi, uvicorn,
  pydantic v2) e `Dockerfile` próprio (multistage, usuário não-root, uvicorn na
  porta 8001). Validação no container isolado: `/health` 200, `/docs` 200,
  raiz 200, matriz de status POST 201 → 409 (SKU duplicado) → 422 (validação
  Pydantic: sku vazio e quantity negativa), GET list/detail 200, DELETE 204 e
  GET após delete 404.
- **Revisão humana/ajuste manual:** adotado e respeitado o padrão do projeto
  para JSON no `curl` do PowerShell 5.1 (`--data-binary @arquivo`, registrado
  na Aula 4). Nota: o FastAPI devolve **422** (e não 400) para payloads
  inválidos — comportamento padrão e idiomático do framework; a matriz 400 do
  IA-SAFE será revisada quando as rotas-mínimas finais forem alinhadas (item 4).

## [2026-09-16] Aula 4 — Auditoria IA-safe e endurecimento de validações

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Revisão dos arquivos não commitados contra o checklist
  `IA-SAFE.md` (item 4 — "Validações e payload") antes do commit.
- **Prompt:** "Verifique se os arquivos de código não comitados se enquadram
  nas diretrizes de @IA-SAFE.md." (auditoria) e "vamos aplicar os
  aprimoramentos opcionais do item 4."
- **Resultado/Decisão:** auditoria concluída com **conformidade** em todas as 7
  seções (escopo sem JWT/Redis/FastAPI/filas; imports usados; tipagem
  adequada; status 200/201/204/400/404 via DRF; segredos via env; operação
  validada no container). Aprimoramentos do item 4 aplicados em
  `api/core/serializers.py`: `_strip_required` (nome/marca/modelo sem espaços
  em branco) e `validate_specifications` exigindo objeto JSON (`dict`).
- **Revisão humana/ajuste manual:** confirmado que o DRF já trima whitespace
  por padrão (`trim_whitespace=True`), então `_strip_required` atua como defesa
  explícita (não como correção de falha real). Testado no container: POST com
  trim → 201, brand/name só espaços → 400, specifications lista → 400, nome de
  categoria duplicado → 400 (`UniqueValidator` automático), preço negativo →
  400 (sem regressão). README atualizado com as novas validações.

## [2026-09-16] Aula 4 — Decisões de arquitetura da API DRF

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 4 — antes de implementar, alinhar banco de dados,
  servidor WSGI e formato da coleção de rotas.
- **Prompt:** "Levando o spec da Aula 4 em consideração, vamos implementar a
  estrutura inicial da API principal usando Django REST Framework. Antes de
  fechar o plano, preciso alinhar: banco (PostgreSQL do compose ou SQLite),
  servidor (runserver ou gunicorn) e formato da coleção (Postman ou Insomnia).
  E, sendo uma loja de produtos eletrônicos, os models devem ser adaptados."
- **Resultado/Decisão:** squad optou por PostgreSQL via compose (reaproveita a
  `DATABASE_URL` da Aula 3), gunicorn com `migrate` no startup e coleção
  Postman. Models adaptados ao domínio de eletrônicos: `brand`, `model`, `sku`
  único, `price` (DecimalField), `specifications` (JSONField), `warranty_months`
  (PositiveIntegerField) e FK `category` (CASCADE).
- **Revisão humana:** planos de campos e decisões aprovados antes do código.

## [2026-09-16] Aula 4 — Implementação do CRUD (models, serializers, viewsets)

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 4 — criar `Category` e `Item` com Models,
  Serializers e ModelViewSets, rotas em `/api/v1/` via `DefaultRouter` e
  migração inicial.
- **Prompt:** "Implemente a estrutura inicial da API DRF seguindo o plano
  aprovado: projeto Django em `api/config`, app `core`, serializers com
  validações customizadas (preço não-negativo, SKU, nome não-vazio), viewsets e
  router; healthcheck `/health` preservado no compose."
- **Resultado/Decisão:** criados `api/manage.py`, `api/config/`
  (settings/urls/wsgi/asgi), app `core`, `requirements.txt` com Django 5.2,
  DRF, dj-database-url, psycopg e gunicorn; Dockerfile passou a executar
  `migrate --noinput` + gunicorn; `.env.example`/compose ganharam
  `DJANGO_SECRET_KEY` e `DJANGO_DEBUG`; removido `api/main.py` (servidor stdlib
  da Aula 3).
- **Revisão humana/ajuste manual:** primeiro boot falhou com
  `ModuleNotFoundError: No module named 'config'` (o worker do gunicorn não
  tinha `api/` no `sys.path`). Corrigido manualmente com
  `sys.path.insert(0, ...)` em `api/config/wsgi.py` e `asgi.py`. Checklist
  IA-safe aplicado: sem imports de JWT/Redis/FastAPI/mensageria, tipos
  adequados e validações antes de persistir.

## [2026-09-16] Aula 4 — Validação, checklist IA-safe e documentação

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** DoD da Aula 4 — testar rotas via requisições (Postman/curl),
  criar o checklist no repositório, exportar coleção e documentar.
- **Prompt:** "Valide a matriz de status HTTP do DoD (200/201/204/400/404) via
  curl no ambiente conteinerizado e documente no README e PROMPTS."
- **Resultado/Decisão:** criado `IA-SAFE.md`, `collections/
  synapseshop_aula4.postman_collection.json` e seção "Rotas da API (Aula 4)" no
  README. Validação com `curl` (corpos via arquivo no PowerShell):
  POST 201, GET 200, PATCH 200, DELETE 204 (e 404 no re-GET), 400 para preço
  negativo, SKU malformado, pk inválida, SKU duplicado e nome vazio; `/health`
  200; cascade em DELETE de categoria confirmado.
- **Revisão humana:** nota do PowerShell 5.1 quebrando aspas de JSON no `curl`
  (contorno com `--data-binary @arquivo`); pendente validação da squad e do
  commit/push.

## [2026-09-14] Aula 3 — Dockerfile com runtime, usuário não-root e cache

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 3 — geração do `Dockerfile` atendendo a *runtime*,
  usuário não-root e uso de cache, com revisão de camadas.
- **Prompt:** "criar um 'Dockerfile' que atenda aos requisitos de runtime,
  usuário não-root e uso de cache. A cada passo faça comentários à respeito do
  que está sendo feito."
- **Resultado/Decisão:** `Dockerfile` baseado em `python:3.12-slim`, usuário
  não-root `appuser` (`useradd` + `USER`), cache em duas camadas: (1) `COPY
  requirements.txt` antes do código para a instalação virar camada cacheável e
  (2) `--mount=type=cache,target=/root/.cache/pip` (BuildKit) reutilizando
  downloads do pip entre builds. Criados `requirements.txt` (placeholder, sem
  frameworks) e `.dockerignore` (exclui `node_modules`, `.venv`, `.env`,
  diagramas etc.), reduzindo o build context de vários MB para ~48 kB.
  Validação com `docker build`, `docker compose up` e `docker history`.
- **Revisão humana:** validado na sessão; camadas analisadas e aceitas.

## [2026-09-13] Aula 2 — Validação de conteinerização e correção do WSL

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 2 (esqueleto em camadas e conteinerização) —
  atuação como desenvolvedor(a) e DevOps.
- **Prompt:** "Atue como as skills desenvolvedor/devOps me ajudando a fazer as
  especificações da spec da Aula 2."
- **Resultado/Decisão:** Estrutura `api/`, `services/`, `repositories/`,
  `Dockerfile` e `docker-compose.yml` já entregues no commit `ec76eed` foram
  revisadas e validadas conforme os requisitos da spec. O ambiente foi
  levantado com `docker-compose up` (doD atendido): container `synapseshop_app`
  subiu e imprimiu "SynapseShop container iniciado". Para destravar o Docker
  Desktop (erro "WSL needs updating"), o WSL foi atualizado para 2.7.14 via MSI
  oficial do repositório microsoft/WSL com instalação elevada.
- **Revisão humana:** pendente de validação pela squad (revisão do commit e da
  evidência de execução do `docker-compose up`).

## [2026-09-14] Aula 3 — Orquestração API + PostgreSQL e segredos em .env

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 3 — orquestrar a API simultaneamente com o banco
  de dados usando o `docker-compose.yml`, com injeção de variáveis mínimas.
- **Prompt:** "criar/configurar o arquivo docker-compose.yml para orquestrar a
  API simultaneamente com o banco de dados... Estou curioso com a presença da
  senha e usuário no arquivo docker-compose.yml. Isso é boa prática ou é melhor
  passar pra um arquivo .env?"
- **Resultado/Decisão:** `docker-compose.yml` com dois serviços: `api` (build
  do Dockerfile, `DATABASE_URL` injetada, inicia após `db` saudável via
  `depends_on` + `service_healthy`) e `db` (`postgres:16-alpine`, credenciais,
  volume `pgdata` e healthcheck `pg_isready`). Credenciais **não** ficam
  hardcoded: passam para `.env` (gitignored, carregado automaticamente pelo
  Compose) com `.env.example` versionado e interpolação `${VAR:-default}`.
  Validação: `docker compose up`, `ps` com ambos Up, rede interna resolvendo o
  hostname `db` (172.18.0.3) e logs do banco prontos.
- **Revisão humana:** decisão de mover credenciais para `.env` adotada pela
  squad na sessão; container órfão da versão anterior removido.

## [2026-09-14] Aula 3 — Rota /health, healthcheck e documentação de infra

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 3 — implementar a rota `/health` para checagem de
  disponibilidade, analisar os logs de inicialização e registrar a
  documentação de infraestrutura (README) e transparência (PROMPTS).
- **Prompt:** "vamos registrar a documentação de infraestrutura no README.md e
  manter a transparência atualizando o arquivo PROMPTS.md. E já vamos também
  seguir com a implementação da rota /health para checagem de disponibilidade
  e para realizar a análise dos logs de inicialização do sistema."
- **Resultado/Decisão:** criado `api/main.py` com servidor HTTP de **stdlib**
  (`http.server`) expondo `GET /health` → `200 {"status": "ok",
  "service": "synapseshop-api"}` (sem framework, respeitando o escopo da Aula
  3), logando cada requisição e imprimindo o startup. `Dockerfile` passou a
  executar `python -u api/main.py`. `docker-compose.yml` mapeou `8000:8000` e
  ganhou healthcheck da API com `urllib` em `/health`. `README.md` documentado
  (subir/validar/logs/derrubar) e `PROMPTS.md` atualizado. Validação: `curl
  http://localhost:8000/health` (200) e análise dos logs de inicialização.
- **Revisão humana:** escopo do `/health` limitado a "ok" (sem checagem de
  banco nesta fase); commit local sem push nesta etapa.

## [2026-09-14] Aula 3 — Multistage build (fechamento do DoD)

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Verificação do item 4 (Definition of Done) da spec da Aula 3 —
  identificado o pendente "o `Dockerfile` implementa multistage build".
- **Prompt:** "seguindo as diretrizes da specs/specs_da_aula_3.md, vamos
  verificar se tudo está feito conforme o que está sendo pedido no item 4
  Requisitos de Entrega (Definition of Done). O banco de dados que usamos é
  complexo ou microserviço?"
- **Resultado/Decisão:** checklist do DoD: 7/8 já atendidos (não-root,
  compose API+DB, `/health`, PROMPTS, README, up único, escopo isolado).
  Esclarecido que o `postgres:16-alpine` **não** é banco complexo nem
  microserviço (é serviço de infraestrutura, sem código de aplicação — o item
  8 segue atendido). **Correção aplicada:** Dockerfile migrado de estágio
  único para **multistage build** — estágio `builder` (`pip install
  --prefix=/install` com cache mount) e estágio `runtime` (`COPY --from=builder`,
  usuário não-root, código por último). Imagem final menor: 188 MB vs 205 MB
  da versão de estágio único; cache de camadas e cache mount preservados.
  Validado com `docker compose up`, `curl /health` (200) e `ps` (api e db
  healthy).
- **Revisão humana:** multistage adotado pela squad; nova rodada de validação
  sem regressões (runtime como `appuser`/uid 1000 confirmado).

## [2026-09-21] Aula 6 — Modelagem relacional do User e migrações (spec itens 1–4)

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 6 — modelagem relacional de pelo menos uma
  entidade, índices, integridade e migrações com SQLAlchemy/Alembic no
  PostgreSQL. A squad optou pela **entidade User** usando o auth padrão do
  Django e pelas tabelas do FastAPI (inventory) governadas pelo Alembic.
- **Prompt:** "elaborar uma modelagem relacional para uma entidade User usando o
  sistema de autenticação padrão do Django e usando SQLAlchemy e Alembic para
  evitar conflitos e dar mais liberdade e performance ao FastAPI... O Django
  deve gerenciar suas próprias tabelas e o Alembic vai gerenciar as tabelas do
  FastAPI. Vamos ignorar Token ou Pedido por enquanto." Decisões alinhadas via
  perguntas: (1) divisão de tabelas — Django=`auth_user`, Alembic=`inventory`;
  (2) testes transacionais — script leve de medição sem pytest (suíte fica para
  a Aula 12).
- **Resultado/Decisão:** dois ORMs coexistindo no mesmo banco sem conflito de
  versionamento. Django continua dono do `auth_user` (índice único em
  `username`; sem customizar `AUTH_USER_MODEL`). FastAPI ganhou modelo
  `InventoryItem` (`inventory_items`) em SQLAlchemy 2.0 com PK, UNIQUE INDEX em
  `sku` (índice essencial) e CHECKs `>= 0`; camadas `repositories/` e
  `services/` (fronteira transacional commit/rollback); `alembic/env.py` com
  filtro `include_object` para o autogenerate nunca tocar as tabelas do Django;
  migração inicial `a7f9e2c1b4d8_inventory_items.py`; Dockerfile/compose
  passaram a aplicar `alembic upgrade head` no startup com `depends_on` no banco.
- **Revisão humana/ajuste manual:** `alembic check` apontou pendência de
  `comment` na coluna `sku` → corrigido na migração e reaplicado (downgrade →
  upgrade); `check` voltou a reportar "No new upgrade operations detected".
  Rollback validado: `downgrade -1` removeu `inventory_items` e manteve as
  tabelas do Django intactas. Qualidade validada com `ruff` e `mypy` (0 erros).

## [2026-09-21] Aula 6 — Repositórios, serviço, medições e registro (spec itens 5–8)

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 6 — implementar repositórios transacionais, o
  serviço que os consome, realizar testes transacionais iniciais, coletar
  tempos e registrar formalmente as decisões técnicas no repositório.
- **Prompt:** "vamos executar esse plano" (plano aprovado da Aula 6: camadas
  Repository/Service, rotas via `Depends`, script `measure_transactions.py`,
  decisões técnicas no README, migrações via Docker).
- **Resultado/Decisão:** `InventoryRepository` (CRUD sobre `Session`) e
  `InventoryService` (regras 200/201/204/400/404/409 + commit/rollback) no
  serviço; rotas agora dependem do serviço; `InventoryItem` (schema) ganhou
  `id`/`created_at`/`updated_at` e `from_attributes`. Script de medição
  executado no container (50 itens, 1 commit/op): create ~7–13 ms/op, lookup
  por SKU ~0,9–2,3 ms (índice único), list ~3,4 ms, update ~5,5–16 ms, delete
  ~5,6–15 ms; rollback demonstrado (linha de transação abortada não persistida)
  e coexistência `auth_*` + `inventory_items`/`alembic_version` confirmada no
  `information_schema`. Decisões técnicas registradas na seção da Aula 6 do
  README (incl. descarte documentado do CHECK `reserved <= quantity`).
- **Revisão humana/ajuste manual:** matriz de status revalidada via API real
  (POST duplicado 409, GET inexistente 404, PATCH parcial 200, DELETE 204);
  tempos coletados em duas rodadas registrados no README.
## [2026-09-21] Aula 6 - Indices essenciais por modelo (User, Item, Category, InventoryItem)

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 6 (modelagem/indices) - complementar a cobertura de indices dos modelos de dominio ja iniciada (PK + UNIQUE sku do inventory).
- **Prompt:** 'Levando em conta todos os modelos do projeto (Django: Users, Item, Category, FastAPI: InventoryItem), vamos desenvolver indices essenciais para cada uma delas.'
- **Resultado/Decisao:** auditoria via pg_indexes + consultas reais (ItemViewSet/Admin). Category e InventoryItem ja cobertos; duas lacunas reais. Item ganhou core_item_created_at_desc_idx (Index desc via Meta.indexes, migracao core 0002) para o ORDER BY -created_at da API/Admin. User ganhou uth_user_email_idx (data migration core 0003 com RunSQL, reverse_sql de rollback) pois o contrib nao indexa email - governanca preservada (Django dono do auth_user; Alembic intocado, lembic check segue limpo).
- **Revisao humana/ajuste manual:** opcoes de escopo apresentadas ao time (email agora vs Aula 7; created_at simples vs composto) - confirmado entrar agora com created_at simples. makemigrations travou no Python 3.14 local; migracoes escritas manualmente e validadas por paridade no container (makemigrations --check = 'No changes detected').


## [2026-09-21] Aula 6 - Corrigindo timeout do makemigrations/migrate no venv local

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** comando makemigrations core no venv local dava timeout (120s) sem saída; manage.py check funcionava.
- **Prompt:** 'Eu reparei que o makemigrations e o migrate no .venv estava dando timeout. Isso foi resolvido?'
- **Resultado/Decisao:** nao era o Python 3.14 — era conectividade. O servico db do compose nao publicava a porta 5432 e o default do settings apontava para localhost:5432, logo o makemigrations (que consulta django_migrations via MigrationRecorder) travava na conexao psycopg. Resolvido pela opcao B: ports: [5432:5432] no servico db + DATABASE_URL local montada a partir do .env (credenciais reais, nao o default synapse/synapse/synapse). Valorizado com makemigrations --check/dry-run = No changes detected e migrate --noinput = No migrations to apply, sem travamento.
- **Revisao humana/ajuste manual:** container db recriado (dados preservados via volume pgdata); conectividade confirmada com psycopg no host (banco/usuario reais); fluxo docountado na secao Aula 6 do README (comandos locais + observacao dos dois caminhos de DATABASE_URL, db:5432 vs localhost:5432).


## [2026-09-21] Aula 6 - Demonstracao dos rollbacks seguros (Alembic + Django) no mesmo banco

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** DoD da Aula 6 exige 'Rollback seguro demonstrado e validado'. O rollback do Alembic havia sido demonstrado na sessao anterior; faltava demonstrar o rollback das migracoes Django (0003/0002) e a prova de isolamento entre os dois versionamentos.
- **Prompt:** confirmes que 'versionamento do schema de forma segura foi bem configurado' e que os 'rollbacks seguros das migracoes foram demonstrados e validados' - o time pediu para comprovar, executar e documentar (sem commit).
- **Resultado/Decisao:** auditoria read-only comprovou a configuracao (ver env.py include_object, cadeia linear a7f9e2c1b4d8, alembic current/check, django_migrations 0001-0003). Executadas 4 etapas: (1) lembic downgrade -1 removeu inventory_items e zerou alembic_version, deixando auth_user/core_item/django_migrations intactos; (2) lembic upgrade head restaurou tabela + ix_inventory_items_sku, alembic check limpo; (3) migrate core 0001 desfez 0003 (reverse_sql do email) e 0002 (RemoveIndex do created_at), preservando 13 colunas e a linha de core_item; (4) migrate core reaplicou ate o head. Isolamento comprovado: durante o rollback do Alembic o django_migrations nao mudou e vice-versa; ao final alembic check + migrate --plan + makemigrations --check todos convergem em 'sem mudancas'.
- **Revisao humana/ajuste manual:** nenhum commit/push foi feito (decisao do time); evidencia registrada no README (tabela de checkpoints por etapa) e neste PROMPTS.md.


## [2026-09-23] Aula 7 - Autenticacao JWT (SimpleJWT) com papeis admin/user, throttling e segredos no .env

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 7 (JWT + papeis + throttling + paginacao/filtros + colecao Postman). Decisao do time: aproveitar o sistema de autenticacao do proprio Django (auth_user + Groups, sem customizar AUTH_USER_MODEL) e concentrar a entrega no DoD da aula.
- **Prompt:** 'Me ajude com as tarefas e responsabilidades das specs_da_aula_7.md fornecendo comentarios explicando o que esta sendo feito. Podemos nos aproveitar do sistema de autenticacao do proprio Django. Nao faca commits locais por enquanto.' Escopo alinhado via perguntas: bullet 1 (indices/rollback/repositorio) tratado como texto legado da Aula 6 e excluido; matriz de permissoes escolhida = catalogo publico (GET), escritas autenticadas (POST user/admin) e rotas administrativas admin-only (PUT/PATCH/DELETE); filtros via django-filter.
- **Resultado/Decisao:** implementado SimpleJWT (obtain/refresh/verify sob /api/v1/auth/ com ScopedRateThrottle 'login' 5/min), Direito de acesso por Grupo (core/permissions.py IsAdminRole), throttling global (anon 20/min, user 100/min) + paginacao PageNumberPagination (PAGE_SIZE=20) + filtros (ItemFilter django-filter: category/is_active/min_price/max_price) + Search/Ordering. Command seed_auth cria grupos admin/user e usuarios demo. Segredos movidos para .env (DJANGO_SECRET_KEY, JWT_SIGNING_KEY, DJANGO_DEBUG; .env.example com placeholders; compose injeta JWT_SIGNING_KEY). Colecao Postman nuevasynapseshop_aula7 com cenario de sucesso, erro, 401/403/429 e auto-set de tokens.
- **Revisao humana/ajuste manual:** teste end-to-end no container validou 200/201/204/400/401/403/429/404. Ajuste de design: filtro de categoria trocado para NumberFilter sobre category_id (id inexistente retorna lista vazia 200 em vez do 400 do ModelChoiceFilter padrao). Troca de senha em seed_auth so no primeiro import (nao sobrescreve edicao manual). Nenhum commit/push (decisao do time); evidencias no README (matriz de permissoes, rotas, segredos, DoD) e nesta entrada.

## [2026-09-28] Aula 8 - Cache-aside com Redis, invalidacao por evento, metricas de hit rate e medicao antes/depois

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 8 (cache-aside com Redis: padrao em listagem e em consulta mais pesada, TTL 60s/300s, invalidacao por evento de dominio, comparacao de latencia/p95/RPS antes e depois, exposicao de hit rate). Escopo alinhado via perguntas com o time: cachear apenas o catalogo existente (Item + Category) em vez de criar Pedido; sem Kafka/RabbitMQ (Aulas 9-11) e sem cabeçalho X-Cache nem management command; extras aprovados = acao `detalhes`, script de medicao e log JSON; `/api/v1/cache/metrics/` restrito ao papel admin; comentarios em portugues no codigo; sem commits.
- **Prompt:** "vamos executar esse plano" (plano aprovado da Aula 8: core/cache.py como ponto unico de cache-aside, sinais post_save/post_delete com transaction.on_commit, contador de geracao INCR para invalidar listagens, TTLs 60s/300s, logger JSON core.cache, endpoint de metricas, scripts/measure_cache.py e secao da Aula 8 no README).
- **Resultado/Decisao:** redis:7-alpine no compose (db 1 exclusivo, sem RDB/AOF, healthcheck, `depends_on: service_healthy`); backend nativo `django.core.cache.backends.redis.RedisCache` + `redis-py` (sem django-redis). `core/cache.py` (miss->consulta->SETEX, hit, fail-open com log `CacheDegradado`), `core/logging_utils.py`, `core/cache_metrics.py` (contadores thread-safe, hits/(hits+misses) por namespace), `core/signals.py` (Item/Category -> `delete` do detalhe + `INCR` do contador de geracao, tudo em `transaction.on_commit`; alterar categoria invalida tambem a listagem de itens por desnormalizacao). Chaves `item:list:g{ger}:{hash}` / `categoria:list:g{ger}:{hash}` (hash = fingerprint dos filtros que mudam o resultado) e `item:{id}` / `item:{id}:detalhes`; TTL 60s/300s via `CACHE_TTL_LIST`/`CACHE_TTL_DETAIL`; `CACHE_ENABLED=false` como switch de baseline. Consulta pesada nova em `GET /api/v1/items/{id}/detalhes/` (4 SELECTs: agregacoes da categoria + mais caros + recentes). Detalhe com filtro/busca faz bypass para preservar o 404 do banco. Medicao (501 itens, 100 requisicoes/endpoint, cliente sequencial): media 48,58 -> 30,70 ms (-36,8%), p95 de 71,50 -> 39,58 ms na consulta pesada, RPS 21,0 -> 32,6 (+55,1%), hit rate 99,0% (413/417).
- **Revisao humana/ajuste manual:** tres bugs reais encontrados na validacao end-to-end e corrigidos. (1) `ItemDetalheSerializer.categoria` era omitido em silencio (o DRF faz `SkipField` quando o `source` implicito nao existe no model) - resolvido com `source="category"`. (2) `CACHE_ENABLED` comparava a string com "True", entao `CACHE_ENABLED=true` (minusculo, como manda a convencao) era ignorado e o benchmark "com cache" media 100% de bypass; trocado por leitura tolerante a caixa. (3) Com o Redis parado a API devolvia 500: o `SimpleRateThrottle` do DRF le o cache `default` em toda requisicao (e nao existe setting `THROTTLE_CACHE`), entao o cache-aside virava ponto unico de falha; criado `core/throttling.py` com as classes apontando para um alias LocMemCache, preservando as cotas da Aula 7 - testado que com o Redis fora a API responde 200 (com ~3,4 s de latencia pelo time-out de socket) e que 20/min continua valendo. Corrigidos ainda o `HTTPError` do script de medicao (variavel `corpo` indefinida) e o `--seed` (sys.path para `config.settings` dentro do container); a coluna de cold-start passou a medir a 1a requisicao antes do aquecimento, porque o parametro `?__miss=` geraria a mesma fingerprint (so filtros conhecidos entram no hash) e mediria um HIT. Registrado em .env.example, README (secao da Aula 8 com as medicoes) e nesta entrada. Nenhum commit/push (decisao do time).


## [2026-10-01] Aula 9 - Mensageria assincrona com RabbitMQ: contrato de evento, idempotencia, reentrega com backoff e DLQ

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 9 (processamento assincrono por eventos: fila duravel, consumidor independente, contrato versionado, idempotencia ponta a ponta, DLQ, publisher confirms). Decisao do time apos comparar as opcoes: RabbitMQ em vez de Kafka, porque a topologia necessaria aqui e filas com TTL e dead-letter, nao log distribuido com retencao. Escopo alinhado via perguntas: manter o broker ja previsto no roadmap (RabbitMQ), documentar o por, e nao criar commits.
- **Prompt:** pedido de implementacao da spec da Aula 9 com o plano aprovado: novo servico `rabbitmq` e `worker` no compose, `api/core/messaging/` (topologia, contrato, produtor, consumidor, dedupe, metricas), `Idempotency-Key` no POST de pedidos, `scripts/measure_messaging.py` e secao da Aula 9 no README.
- **Resultado/Decisao:** `rabbitmq:3.13-management-alpine` e `worker` (mesmo codigo Django, sem ORM duplicado) no compose; modulo `core/messaging` com exchange `pedidos` (topic), fila `pedidos.criados`, escada de retry `pedidos.criados.retry.1/.2/.3` (TTL 5/15/45 s, DLX de volta a fila principal) e DLQ terminal `pedidos.criados.dlq`. Contrato `PedidoCriado` v1 em `docs/contracts/pedido_criado.md`, com `publicado_em` em epoch ms e valores monetarios como string (Decimal nao e JSON). Duas barreiras de idempotencia: janela no Redis (SET NX EX) e `UPDATE` condicional no PostgreSQL como autoridade final. `auto_ack=False` com `basic_ack` somente depois do efeito; publisher confirms + `mandatory=True` para o POST responder 201 so com persistencia confirmada (503 e `pendente_publicacao` caso contrario, com `manage.py republicar_pedidos` para recuperar). Falha injetada via `X-Simular-Falha: 1` lida do banco pelo consumidor, para provar a escada ponta a ponta.
- **Revisao humana/ajuste manual:** medicao real (20 pedidos + 3 reenvios + escada) validou latencia publicacao->processado de 82,35 ms em media (p50 75 ms, p95 124 ms), idempotencia confirmada nos 3 reenvios (HTTP 200, mesmo pedido) e escada medida em t+0 / 6,1 / 21,3 / 66,8 s, coerente com os degraus 5/15/45. Corrigido o rotulo do header de tentativa (`x-tentativa`, nao `x-pedido-tentativa`) no contrato e no README. Nenhum commit/push (decisao do time).


## [2026-10-01] Aula 10 - Vazao, multiplos consumidores e trade-offs (latencia x throughput x idempotencia)

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** Spec da Aula 10 pede Apache Kafka, medicao de throughput, discussao de trade-offs entre dedupe/latencia/throughput e uso de multiplos consumidores. O time decidiu manter **RabbitMQ** (consistente com a Aula 9) e registrar o desvio de forma explicita, em vez de trocar de broker no meio do caminho. Sem commits.
- **Prompt:** pedido de conclusao do DoD da Aula 10 com o plano aprovado: ampliar `scripts/measure_messaging.py` com carga concorrente (`--carga`, `--concorrencia`), inspecao da DLQ sem consumir (`--inspecionar-dlq`), analise do log transacional (`--analisar-logs`) e contagem de consumidores; executar as medicoes com 1 e 3 workers, com Redis fora do ar e com worker morto no meio; documentar no README e no contrato.
- **Resultado/Decisao:** medicao com 1 consumidor (n=20): media 85,9 ms (p50 80, p95 112). Sob carga (60 pedidos, 8 POSTs em paralelo): 11,46 POST/s e 7,23 pedidos/s ponta a ponta, latencia de 4.549 ms em media. Com 3 consumidores (`docker compose up -d --scale worker=3`, possivel porque o service nao tem `container_name`): 7,13 pedidos/s e latencia de 4.720 ms - **sem ganho, e um pouco pior**, e o log explica por que: `duracao_ms` media de 12,9 ms (p50 10,9) e `atraso_fila_ms` p95 de 29 ms mostram que o consumidor tem folga de ~77 mensagens/s por instancia e a fila nunca acumula. O gargalo esta antes, na publicacao: `PedidoPublicado.duracao_ms` p50 de 29,8 ms e **uma `TopologiaDeclarada` por publicacao** (164 declaracoes para 164 POSTs nas duas rodadas), porque cada POST abre conexao AMQP nova e redeclara a topologia. Triplicar a concorrencia do cliente (8 -> 24) nao aumentou a vazao (10,0 POST/s) e apenas elevou o POST para 1.849 ms. A distribuicao entre consumidores foi 20/20/20 nas 60 mensagens da carga, provando o round-robin. Dedupe fail-open com Redis parado: 10/10 pedidos processados, latencia de 70 ms -> 3.437 ms, idempotencia preservada pelo `UPDATE` condicional. At-least-once: `SIGKILL` nos 3 consumers durante a carga (60/60 processados, 0 na DLQ, filas vazias).
[NOTA DE CONTINUIDADE — a entrada acima e o registro da primeira rodada da Aula 10, com o desvio para RabbitMQ. A implementacao foi revisada e o broker padrao passou a ser o Apache Kafka; o registro completo da rodada Kafka esta na entrada seguinte.]

- **Revisao humana/ajuste manual:** os tres maiores problemas encontrados foram **no instrumento de medicao**, nao no sistema de mensageria, e foram corrigidos. (1) A API grava `status=falha` antes de publicar na DLQ - com snapshots finos, o instante do `falha` foi t+68,1s com `DLQ=0, retry.3=1`, entao o `sleep(2)` fixo entre "API disse falha" e "ler as filas" produzia `dlq=0` ou `dlq=1` conforme o jitter; substituido por `aguardar_mensagem_na_dlq()`, que pergunta ao broker e reporta quanto esperou. (2) `docker compose up --scale worker=3` recriou a API com `DRF_USER_RATE` no padrao de 100/min porque a variavel de ambiente nao existia naquele shell, e 11 respostas 429 (18 s cada) empurraram a latencia media da carga para 53 s (contra ~4,5 s na rodada limpa) - com o relatorio saindo limpo e bonito. Agora todo 429 e contado, a execucao sai com codigo 1 e `--tolerar-429` (padrao 0) so permite publicar numeros sem throttling. (3) Derrubar a API no meio da carga matava o harness com `http.client.RemoteDisconnected`, que nao e `URLError`; `OSError`/`HTTPException` passaram a entrar na fila de retentativa, em contador separado do 429. Corrigidos tambem 4 apontamentos preexistentes do ruff no pacote de mensageria (ordem de imports, `Decimal(1)`, `noqa` nao usado, anotacao sem aspas), um sombreamento do nome `erro` no produtor e um `Topologia | None` acessado 6 vezes sem checagem (virou property com erro explicito). Nao foi reproduzida duplicata em si: a janela entre commit e `basic_ack` e de sub-milissegundo, e provar isso exigiria um ponto de injecao de falha (ex.: `X-Simular-Quase-ack`) - registrado como limitacao honesta em vez de afirmacao sem evidencia. (4) O erro mais caro foi comparar execucoes de sessoes diferentes: ao conferir o DoD, a perna de 1 consumidor veio de uma sessao em que o mesmo codigo rendeu 9,29 ped/s, e a de 3 consumidores de outra. A variacao entre sessoes (~22% na vazao, ~38% na latencia) era do mesmo tamanho do efeito que se queria medir, e a comparacao teria concluido que 3 consumidores deram +20% de vazao - o oposto do que a medicao pareada mostra. As duas colunas foram reexecutadas encostadas (mesma sessao, 429 = 0 nas duas) e viraram a tabela do README, com uma secao nova explicando o por. Nada foi "adicionado e comemorado" para melhorar o numero: o gargalo do produtor (pool de conexao) fica medido e diagnosticado para a aula seguinte. Nenhum commit/push (decisao do time).


## [2026-10-03] Aula 10 (revisao) - Apache Kafka como broker padrao, com RabbitMQ por profile

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** a decisao da entrada anterior (manter RabbitMQ e registrar o desvio) foi revista: a spec da Aula 10 pede Apache Kafka, e a implementacao passa a ter o Kafka como broker **padrao**, com `MENSAGERIA_BROKER` escolhendo entre `kafka` (padrao) e `rabbitmq` (profile). A topologia agora e a do Kafka - topico com 3 particoes, retencao por topico, offsets confirmados, DLQ terminal - e RabbitMQ continua funcionando para comparacao, sem duplicar ORM nem views. Sem commits.
- **Prompt:** conclusao do DoD da Aula 10 sobre Kafka: topicos/particoes/retencao, produtor com `acks=all` e idempotencia, consumidor com commit manual apos o efeito, escada de reentrega 5/15/45 s por **retencao de topico** (sem `sleep` no worker), DLQ terminal, comandos de administracao/inspecao/reset de offsets, `scripts/measure_messaging.py` para os dois brokers, e medicao de latencia e throughput validando o paralelismo.
- **Resultado/Decisao:** topicos `pedidos.criados` (3 particoes, retencao 7 dias), `pedidos.criados.retry.1/2/3` (1 particao cada, retencao 610/630/690 ms = backoff 5/15/45 s) e `pedidos.criados.dlq` (retencao 30 dias, sem consumidor). Chave de producao = `str(pedido.id)`, entao todos os eventos de um pedido caem na mesma particao e a ordem por pedido e preservada. O degrau de reentrega e a propria retencao do topico: o replayer (`synapseshop-replay`) republica no principal quando o offset e anterior a `agora - backoff`, e **nao ha timer no processo**, o que evita a espera perdida quando o worker reinicia. Produtor singleton por processo (`acks=all`, `enable.idempotence=true`, `flush()` antes do 201) e consumidor com `enable.auto.commit=false` + `enable.auto.offset.store=false`, uma mensagem por `poll()` e commit so apos o efeito.
- **Resultado/Decisao:** E2E validado ponta a ponta: POST 201 e processamento em ~31-45 ms; reenvio com a mesma `Idempotency-Key` devolve **HTTP 200** com o mesmo `pedido_id` e sem evento novo; `X-Simular-Falha: 1` percorre retry.1/2/3, chega a `pedidos.criados.dlq` e termina em `status = falha` com **`tentativas = 4`** (1 tentativa inicial + 3 reentregas) em ~72-80 s.
- **Resultado/Decisao:** indisponibilidade do broker: com `docker compose stop kafka`, o `POST /pedidos/` devolve **HTTP 503** e o pedido fica em `pendente_publicacao`; depois `manage.py republicar_pedidos` publicou o pedido 2796 (offset 592) e o worker o levou a `processado`. O pedido e gravado mesmo com o broker fora - **503 honesto e recuperavel**, nao pedido fantasma. Dedupe fail-open com Redis parado: `POST` 201 e reenvio 200 com o **mesmo** `id` (`2797`), sem warning de dedupe, porque o `UPDATE` condicional no banco e a autoridade final.
- **Resultado/Decisao:** latencia em repouso (n=10): publicacao -> `processado` media 152 ms (p50 100, p95 640); POST media 162 ms (p95 659), o preco do `acks=all`. Sob carga (n=30, 8 em paralelo): 9,27 POST/s na publicacao e 6,97 pedidos/s ponta a ponta, com latencia p50 de 2.229 ms.
- **Resultado/Decisao (paralelismo):** medido pelos **timestamps do log do worker**, filtrando a rajada pelo prefixo da `chave_idempotencia` - a vazao e a distancia entre a primeira e a ultima `MensagemRecebida` da rajada, e nao ha relogio de script na conta. Rajada de 600 mensagens publicada com o worker parado, as duas pernas encostadas na mesma sessao: **1 consumidor = 8,53 s = 70,2 msg/s; 3 consumidores = 9,68 s = 61,9 msg/s.** Ou seja, **3 consumidores foram 12% MAIS LENTOS que 1** - o paralelismo nao paga nesta configuracao. A particao-por-consumidor funciona (600 mensagens distribuidas em 197/188/215 e 195/200/205, **0 duplicatas**, 0 `OffsetCommitFalhou`, lag final 0 nos dois cenarios). O custo fixo de entrar no grupo come o ganho: o `duracao_ms` maximo da rajada sobe de 114 ms para **2.881 ms** com 3 containers, ou seja, ~3 s de rebalance em uma rajada de 8,5 s. Some-se o commit sincrono por mensagem (p50 1,30 ms, p95 2,59 ms medidos direto contra o broker; o mesmo lote sem commit vai de 408 para 1017 msg/s), que serializa no broker e nao paraleliza.
- **Revisao humana/ajuste manual (medicao, o segundo erro do mesmo tipo):** a primeira versao desta medicao reportou **167 msg/s com 1 consumidor e 223 msg/s com 3** (ganho de 1,33x) e a conclusao "o broker single-node satura a 227% de CPU, por isso o paralelismo e limitado pelo broker". **Os dois numeros estavam errados e foram corrigidos.** (1) O medidor dividia a soma **acumulada** dos offsets confirmados das 3 particoes pelo tempo (`ultimo/dt`) - um contador que cresce a cada rodada, entao a divisao nao era mensagens/segundo. (2) O mais grave: mesmo com a linha de base correta, o relogio comecava quando o script subia, e o worker comeca a drenar **no instante em que entra no grupo**. Numa rajada de 600 o medidor leu a base em 3445 quando a rajada comecou em 2915 - ou seja, atribuiu ao cronometro uma rajada que ja estava 88% consumida antes do `t0` - e reportou 0,3 msg/s para um drain que ja tinha terminado. A solucao foi mover a medicao para o log do worker, onde o instante de cada mensagem e o registro do proprio broker e a rajada e identificada sem ambiguidade pelo prefixo da chave de idempotencia. (3) A amostra de CPU que "provou" o gargalo no broker foi colhida **depois** do drain terminar, entao media a wrong coisa; foi removida do texto em vez de corrigida por conveniência. Nenhum numero foi mantido por ser uma conclusao mais interessante.
- **Revisao humana/ajuste manual:** o erro mais caro desta rodada foi **medir a vazao pelo relogio do proprio script**. A primeira tentativa publicava uma rajada e ficava fazendo `GET /pedidos/{id}` a cada ~20 ms, medindo **1,0 ped/s** com 1 consumidor; o log do worker da mesma janela provou gap p50 de **46 ms** entre mensagens processadas (~20/s), porque o `GET` custa ~0,8 s nesta pilha (DRF + banco) e o instrumento era mais lento que a coisa medida. A correcao seguinte (medir pelo offset do grupo) tambem estava errada e so depois virou medicao por timestamp do log - a conta completa esta no item de paralelismo acima. Tres outras falhas do mesmo tipo foram corrigidas: o gerador publicava **64 de 60** pedidos pedidos (contagem fora de lock); o intervalo dinamico do Windows tem so 1000 portas (`10000-10999`) e a carga diedo com `WinError 10048` quando roda no host - passou a rodar dentro do container via `docker compose exec`; e o `manage.py` nao estava na imagem recriada, o que fazia `declarar_topicos_kafka --json` estourar com `TypeError: 'ListConsumerGroupsResult' object is not iterable` (codigo novo, imagem velha - a falha parecia bug do codigo e era build desatualizado).
- **Resultado/Decisao (replay, validado):** o reset de offsets so funciona com o **grupo vazio**. Com o worker no ar o comando `declarar_topicos_kafka --resetar-offsets earliest` **retorna sucesso e nao move nada** - o broker aceita o `AlterOffsets` para um grupo estavel, mas o consumidor ja tem a posicao em memoria e segue dela. Medido: com 3 workers, o reset reportou `-> earliest` e os offsets continuaram no fim do log (1379/1355/1386 = watermark), com **zero** mensagens reprocessadas; parando o grupo, o mesmo comando zerou os tres offsets (4120 pendentes) e o replay aconteceu de fato. Essa armadilha quase virou mais um numero errado: a primeira checagem de "a idempotencia sobrevive ao replay" foi feita sobre um replay que **nao tinha acontecido** (0 eventos no log), e a leitura "o banco nao mudou, logo a idempotencia segurou" estavamedindo nada. So depois de zerar os offsets de fato o replay rodou: 4135 `MensagemRecebida` e 4064 `PedidoDuplicado`, com `processado = 4996` e `falha = 24` **identicos antes e depois** - que e a prova de que o efeito e unico com o historico inteiro reprocessado. Os 57 `PedidoFalha` / 14 `PedidoDlq` do replay nao sao defeito: sao os pedidos de E2E com `X-Simular-Falha`, que guardam `simular_falha=True` no banco e por isso reexecutam a escada ao serem relidos - ou seja, **replay de um historico com falhas intencionais repopula a DLQ** (de 6 para 20). Registrado no README.
- **Revisao humana/ajuste manual (codigo):** seis defeitos reais corrigidos. (1) O startup lia `TopicMetadata.config`, que **nao existe** na versao confluent-kafka instalada - Topics ja existentes quebravam no boot. (2) `descrever()` lia offset pelo `Consumer` do proprio processo, o que devolveria o mesmo numero para `synapseshop-pedidos` e `synapseshop-replay` e faria o relatorio mentir sem sinal algum; passou a usar `list_consumer_group_offsets`. (3) **Dupla contagem de `Pedido.tentativas`**: a falha terminal era contada duas vezes (o `UPDATE` de `falha` e a publicacao na DLQ), produzindo 5 tentativas para 4 passagens; agora o banco e a unica fonte. (4) O replayer pausava o consumidor e voltava com `resume()` sem `seek()`, o que deixava a mensagem presa ate um rebalance e queimava o degrau da escada sem tentar; agora guarda o offset pausado, faz `seek()` e depois `resume()`, com espera ate a entrega. (5) `ILLEGAL_GENERATION` no commit durante `--scale` era logado como **ERROR** vermelho, parecendo defeito no consumer quando e o protocolo documentado (a particao ja tem outro dono e quem confirma o offset e ele); agora `_confirmar()` separa os casos e emite `OffsetCommitIgnorado` em INFO, com rebalance forcado no meio do consumo dando **0** falhas. (6) **`resetar_offsets()` nunca funcionou**: `alter_consumer_group_offsets()` foi chamado com posicionais e depois tratado como futuro unico, dando `TypeError: takes 2 positional arguments but 3 were given` e depois `AttributeError: 'dict' object has no attribute 'result'`. A assinatura real recebe uma **lista de `ConsumerGroupTopicPartitions`** e devolve um **dicionario de futuros** (um por requisicao) - as duas hypotheses estavam erradas e so a introspecao da assinatura_installada resolveu.
- **Revisao humana/ajuste manual (documentacao):** `README.md` e `docs/contracts/pedido_criado.md` reescritos para Kafka (topicos, particoes, retencao, offsets, DLQ, reentrega por retencao). Corrigido no contrato que a tabela de eventos da Aula 9 dizia 21 tipos quando o codigo emite 45 - conferido por grep de `"evento":` e nao de memoria. Substituido o `x-death` do RabbitMQ como auditoria de passagem: no Kafka nao existe equivalente, entao a prova passa a ser `x-timestamp-ms` nos headers mais o evento `RetryLiberada` com `espera_ms` (que mede os ~15 s do degrau 2). Registrado que **so 3 consumidores podem trabalhar** (3 particoes; `--scale worker-kafka=5` deixa 2 ociosos) e que aumentar particoes so e possivel para cima, nunca para baixo. `scripts/measure_messaging.py` passou a detectar o broker em `/health` e a trocar so as etapas de broker: no Kafka delega aos management commands (o cliente Python do broker so existe na imagem da API), no RabbitMQ le a management API; latencia, carga e analise de log sao o mesmo codigo nos dois.
- **Revisao humana/ajuste manual (escopo):** nada foi "adicionado e comemorado" para melhorar o numero - o gargalo do broker single-node fica medido e diagnosticado (subir para 3 brokers ou reduzir particoes seria o caminho, e e decisao de infraestrutura, nao de codigo). Nenhum commit/push (decisao do time).


## [2026-10-05] Aula 11 - Pagamento e notificacao como segundo fluxo Kafka

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** DoD da Aula 11 (`specs/specs_da_aula_11.md`): criar pedido, simular pagamento e notificar, orquestrado em contentores, com mensageria, cache, logs, healthcheck e README atualizado. A diretriz SpecDD manda explicitamente nao antecipar testes automatizados, CI/CD ou dashboards.
- **Prompt:** implementar o fluxo pedido ➔ pagamento ➔ notificacao como um **segundo** fluxo Kafka (topico, grupo, offsets, retries e DLQ proprios, com `worker-pagamentos` no Compose), com contrato de evento versionado, idempotencia ponta a ponta, escada de reentrega e DLQ, endpoint de pagamento com idempotencia por chave, listagem de notificacoes com permissoes e filtros, e documentacao (contrato, README e colecao Postman).
- **Resultado/Decisao:** `Pagamento` e `Notificacao` (migration `0005`), com `Pagamento.pedido` como **`OneToOne`**: um pedido aceita um pagamento. `Notificacao.pagamento` tambem e `OneToOne`, e essa e a **terceira** barreira de idempotencia (depois da janela no Redis e do `UPDATE` condicional no PostgreSQL). Topicos `pagamentos.registrados` (3 particoes), `.retry.1/2/3` e `.dlq` (30 dias), grupo `synapseshop-pagamentos`; a politica de reentrega e **compartilhada** com o fluxo de pedidos (5/15/45 s, maximo 3) porque o comportamento identico e o que permite reusar o replayer - o que nao e compartilhado e estado. A chave Kafka do pagamento e o **`pedido_id`**, nao o `pagamento_id`, pela mesma razao do `PedidoCriado` (ordem por pedido preservada).
- **Resultado/Decisao (o `status` e de quem muda):** `registrado` e estado **local do produtor** - a linha foi criada e o evento foi confirmado pelo broker. Quem vira `aprovado`/`recusado` e o worker, no efeito do evento. Se a API fizesse esse `UPDATE`, o `UPDATE` condicional do worker nao encontraria linhas processaveis e a notificacao nunca seria criada. Por isso `status` **nao viaja como `registrado`**: o contrato valida que `status` concorda com `aprovado` (`aprovado` ou `recusado`), porque um evento que mente sobre o proprio desfecho e muito mais dificil de diagnosticar depois do que um payload recusado no contrato. Nao existe `status = falha` no `Pagamento`: o pedido continua `processado` e quem continua pendente e o aviso.
- **Resultado/Decisao (duas flags, e por que as duas):** `PEDIDO_PERMITIR_SIMULACAO_FALHA` e `PAGAMENTO_PERMITIR_SIMULACAO_FALHA` estao ligadas no Compose, e as duas sao consultadas **pela API**, que decide se aceita o header `X-Simular-Falha` e grava `simular_falha`. O worker nao le flag nenhuma: ele honra a marcacao gravada no banco. Sao duas flags (e nao uma) porque a falha injetada leva a mensagem para a **DLQ do seu fluxo** - misturar as duas sabotagens num interruptor so tornaria "qual fluxo parou?" mais dificil de responder. Desligada, a flag ignora o header em silencio (o POST segue normal, DLQ vazia), que e o comportamento correto fora de desenvolvimento.
- **Resultado/Decisao (E2E medido, build final):** pedido 5120 (R$ 699.30, PIX, email) - `POST /pedidos/` 201 e `processado`; `POST /pagamento/` **201** com `status=registrado` e o bloco `evento` (`topico=pagamentos.registrados`, `chave=5120`, particao 1, offset 1); ~7 s depois `status=aprovado`, `notificado_em` preenchido e `GET /notificacoes/?pedido=5120` com `count: 1` ("Seu pagamento de R$ 699.30 via PIX foi aprovado."). Caminho da recusa: pedido 5121 (R$ 899.10, cartao, SMS) - `status=recusado` e uma notificacao "foi recusado: saldo insuficiente". Escada da DLQ medida pelos timestamps do log: intervalos de **6,7 s** e **16,3 s** para backoffs declarados de 5 s e 15 s, e `tentativas=4` em ~67 s, sem notificacao. Permissoes: `demo_user` ve 9 notificacoes, `demo_admin` ve 10, e o usuario nao ve a notificacao do pedido do admin (`count: 0`); anonimo 401.
- **Revisao humana/ajuste manual (reproducao de DLQ que nao reproduzia):** `inspecionar_dlq_kafka --reprocessar` devolvia a mensagem da DLQ ao topico principal **preservando o `x-tentativa`** que veio da escada esgotada. O worker processava uma vez e mandava a mensagem direto de volta para a DLQ, enquanto o comando reportava "1 mensagem devolvida ao topico principal" - e o sintoma (uma mensagem na DLQ que ninguem colocou la) nao aponta para o header. O `--reprocessar` agora descarta `x-tentativa` (volta a 0) e `x-motivo` (que descreve a falha **daquela** tentativa). Validado: pedido 5115 com `X-Simular-Falha`, escada esgotada, `simular_falha` limpo no banco e evento reprocessado - o worker aprovou, criou **uma** notificacao e a DLQ ficou vazia. O mesmo defeito existia nos dois fluxos, porque o comando e o mesmo.
- **Revisao humana/ajuste manual (idempotencia do re-POST):** o `IntegrityError` do `OneToOne` so diz que *este pedido ja tem um pagamento*, nao que ele e o pagamento que o cliente esta tentando criar. Sem comparar a `idempotency_key` (SHA-256 de pedido + metodo + desfecho), um `POST` com `metodo: "boleto"` contra um pedido ja pago com PIX devolvia **200** e o pagamento em PIX - o cliente recebia um "deu certo" para um pedido que nao tentou fazer. Agora: mesma chave e `registrado` republica (200, `republicado: true`, a cura do 503); mesma chave e ja resolvido devolve 200 com `republicado: false` e `evento.duplicado: true` (o gateway ja respondeu, publicar de novo criaria uma segunda notificacao); chave **diferente** devolve **409** com `pagamento_existente` e as duas chaves lado a lado. A republicacao tambem passou a respeitar o canal da requisicao em vez de forcar `email` - `canal_notificacao` nao e persistido no `Pagamento`, entao forcar um default entregaria o aviso no canal que o cliente nao pediu.
- **Revisao humana/ajuste manual (defeitos de codigo encontrados e corrigidos):** (1) `kafka_replayer.py` chamava `self._pausar(mensagem.topic(), mensagem.partition(), 60)` - **3 argumentos** para um metodo que aceita 2, no ramo defensivo de topico de retry desconhecido: um `TypeError` no lugar de uma pausa, e a mensagem nunca retida. (2) O log de espera do replayer preenchia `idade_ms`, que nao estava na whitelist `CAMPOS_EVENTO` do `JsonLogFormatter`, entao o campo documentado **nunca aparecia** em nenhum log; adicionado. (3) `except (TypeError, KafkaError)` em `_confirmar`: `KafkaError` do confluent-kafka nao herda de `BaseException`, entao num `except` ele nunca casa com nada e so pareceria cobrir um erro do broker que aquele ponto nao ve; reduzido a `TypeError`. (4) `declarar_topicos_kafka --purgar` entregava a lista de **objetos** de topologia na posicao em que `purgar` espera os **NOMES** de topico (o primeiro parametro), o que faria apagar/recriar topic pelo nome do objeto em vez de pelo topico de verdade; passou a entregar em `topologias=topologias`, por palavra-chave, que e o parametro que leva os objetos. (5) `NotificacaoViewSet` nao tinha `filterset_fields`, e `?pedido=`/`?canal=` eram ignorados em silencio. (6) O `201` do `POST /pagamento/` nao devolvia o bloco `evento`, mas o re-POST devolvia - o `PedidoCriado` ja devolvia os dados de publicacao no 201; agora os dois caminhos devolvem a mesma forma. (7) O replayer de pagamentos consumia `self._topologia.topicos_retry()` do fluxo de **pedidos** e publicava os retries de pagamento no topico errado. (8) Config morta no `worker-pagamentos`: `PAGAMENTO_PERMITIR_SIMULACAO_FALHA` na env do worker prometia um interruptor de worker que **nao existe** - `_aplicar_efeito_pagamento` so olha `simular_falha` gravado no banco, igual a `_aplicar_efeito_pedido`. Era a mesma armadilha nos dois fluxos, e foi o que mandou a diagnostico errado na sessao (achado conferindo o valor da flag dentro do container, que era `False`, e achando que o reprocessamento falhava por causa disso - o reprocessamento falhava porque o `simular_falha` no banco continuava `true`, e o defeito real era o `x-tentativa` preservado). A env foi removida do worker, e os tres lugares que descreviam a exigencia de "ligar as duas metades" (Compose, `settings.py`, README) foram corrigidos.
- **Revisao humana/ajuste manual (documentacao desatualizada):** `models.py` apontava para `views.PedidoViewSet.pagar` (a acao e `pagamento`); a docstring de `criar_consumidor` dizia que `destino` e ignorado no Kafka quando ele e repassado como `topico`; `inspecionar_dlq_kafka` afirmava "grupo novo a cada execucao" quando `GRUPO_INSPECAO` e fixo - e ele **precisa** ser fixo, porque e o que permite ao `--reprocessar` confirmar o offset; `docs/contracts/pedido_criado.md` ainda citava `contracts.validar_evento`, que nao existe. `PAGAMENTO_PERMITIR_SIMULACAO_FALHA` estava `false` no `.env.example` e `true` no Compose - alinhado.
- **Revisao humana/ajuste manual (verificacoes):** `compileall`, `manage.py check` e `makemigrations --check --dry-run` sem alteracoes apos cada bloco; `docker compose config --services` com 7 servicos; `declarar_topicos_kafka --purgar` validado **sem tocar no broker**, com `purgar` substituido por um duplo que grava os argumentos: o duplo recebeu `topicos=None` e **duas topologias** (uma por fluxo), o que confirma a chamada por palavra-chave - e quem expande objeto em nome de topico (principal + 3 retries + DLQ) e o proprio `purgar`, nao o comando. Auditoria automatizada do `api/` procurando refs antigas, settings do fluxo errado entre os dois fluxos, aridade de chamada divergente e campos de serializer ausentes: os achados foram os 8 acima, nenhum outro.
- **Revisao humana/ajuste manual (escopo):** nada foi antecipado. **Nenhum** teste automatizado, **nenhuma** pipeline de CI/CD, **nenhum** dashboard ou extracao de dados (o `Notificacao` foi modelado com indice por dono e data pensando nas aulas futuras, mas e isso: uma tabela, nao um relatorio), **nenhuma** IA. O RabbitMQ **nao** ganhou o segundo fluxo - implementa-lo exigiria uma topologia AMQP equivalente, e fingir que os dois brokers tm a mesma coisa seria mentir sobre a assimetria. Entregues: `docs/contracts/pagamento_registrado.md`, secao da Aula 11 no `README.md` e `collections/synapseshop_aula11.postman_collection.json` (21 requests na ordem do DoD). Nenhum commit/push (decisao do time).
