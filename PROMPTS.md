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