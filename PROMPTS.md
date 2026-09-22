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
- **Contexto:** comando makemigrations core no venv local dava timeout (120s) sem sa�da; manage.py check funcionava.
- **Prompt:** 'Eu reparei que o makemigrations e o migrate no .venv estava dando timeout. Isso foi resolvido?'
- **Resultado/Decisao:** nao era o Python 3.14 � era conectividade. O servico db do compose nao publicava a porta 5432 e o default do settings apontava para localhost:5432, logo o makemigrations (que consulta django_migrations via MigrationRecorder) travava na conexao psycopg. Resolvido pela opcao B: ports: [5432:5432] no servico db + DATABASE_URL local montada a partir do .env (credenciais reais, nao o default synapse/synapse/synapse). Valorizado com makemigrations --check/dry-run = No changes detected e migrate --noinput = No migrations to apply, sem travamento.
- **Revisao humana/ajuste manual:** container db recriado (dados preservados via volume pgdata); conectividade confirmada com psycopg no host (banco/usuario reais); fluxo docountado na secao Aula 6 do README (comandos locais + observacao dos dois caminhos de DATABASE_URL, db:5432 vs localhost:5432).


## [2026-09-21] Aula 6 - Demonstracao dos rollbacks seguros (Alembic + Django) no mesmo banco

- **Ferramenta:** opencode (opencode/big-pickle)
- **Contexto:** DoD da Aula 6 exige 'Rollback seguro demonstrado e validado'. O rollback do Alembic havia sido demonstrado na sessao anterior; faltava demonstrar o rollback das migracoes Django (0003/0002) e a prova de isolamento entre os dois versionamentos.
- **Prompt:** confirmes que 'versionamento do schema de forma segura foi bem configurado' e que os 'rollbacks seguros das migracoes foram demonstrados e validados' - o time pediu para comprovar, executar e documentar (sem commit).
- **Resultado/Decisao:** auditoria read-only comprovou a configuracao (ver env.py include_object, cadeia linear a7f9e2c1b4d8, alembic current/check, django_migrations 0001-0003). Executadas 4 etapas: (1) lembic downgrade -1 removeu inventory_items e zerou alembic_version, deixando auth_user/core_item/django_migrations intactos; (2) lembic upgrade head restaurou tabela + ix_inventory_items_sku, alembic check limpo; (3) migrate core 0001 desfez 0003 (reverse_sql do email) e 0002 (RemoveIndex do created_at), preservando 13 colunas e a linha de core_item; (4) migrate core reaplicou ate o head. Isolamento comprovado: durante o rollback do Alembic o django_migrations nao mudou e vice-versa; ao final alembic check + migrate --plan + makemigrations --check todos convergem em 'sem mudancas'.
- **Revisao humana/ajuste manual:** nenhum commit/push foi feito (decisao do time); evidencia registrada no README (tabela de checkpoints por etapa) e neste PROMPTS.md.

