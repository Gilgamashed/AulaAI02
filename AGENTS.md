# AGENTS.md

Guia de contexto para agentes de IA trabalhando neste repositório.

## O que é o projeto

**SynapseShop** — backend de pedidos com IA integrada (curso de 25 aulas,
metodologia **SpecDD**). API principal em Django REST Framework, microsserviço
de estoque em FastAPI, PostgreSQL, Redis, RabbitMQ + Kafka, orquestrados com
Docker Compose.

## Regra de escopo (anti-hallucination)

Implemente **apenas** o que a spec da aula corrente pede
(`specs/specs_da_aula_N.md`). Não antecipe modelos, endpoints, libs ou
infraestrutura de aulas futuras. A meta-spec completa está em
`specs/00_diretriz_incremental_specdd.md`.

## Comandos

```bash
docker compose up -d --build          # ambiente completo (api :8000, inventory :8001, dashboard :8501)
docker compose run --rm tests         # suíte pytest com gate de cobertura (85%)
docker compose exec api python api/manage.py seed_auth   # usuários demo
docker compose exec api python api/manage.py seed_demo   # catálogo/pedidos/pagamentos demo
docker compose exec api python api/manage.py indexar_docs # índice RAG (README + OpenAPI)
docker compose run --rm dashboard python -m dashboard.simular_sqli  # simulação SQLi
python scripts/validar_compose.py     # smoke de db/api/dashboard (stack já no ar)
python scripts/validar_mvp.py         # smoke ponta a ponta do MVP (stack já no ar)
python scripts/validar_mvp.py --skip-ai  # smoke sem os passos de IA
python -m ruff check .                # lint
python -m mypy api services dashboard # verificação de tipos
python scripts/lint-openapi.ps1       # valida docs/openapi.yaml (Spectral)
```

## Estrutura

- `api/` — Django (app `core`, mensageria, LLM, RAG em `core/ask_docs/`,
  commands, migrations, mock de front-end em `templates/core/app.html`)
- `services/inventory/` — FastAPI + SQLAlchemy/Alembic
- `dashboard/` — Streamlit (conexão segura, consultas parametrizadas, painel analítico)
- `tests/` — `unit/` e `integration/` (pytest + pytest-django)
- `specs/` — specs incrementais por aula (fonte de requisitos)
- `docs/` — autenticação, contratos de evento, OpenAPI, changelog, aulas e
  material de apresentação
- `scripts/` — medições de cache/mensageria, lint do OpenAPI, smoke do Compose
  e smoke ponta a ponta do MVP
- `.github/workflows/` — pipeline de CI/CD (testes, build, Compose, DockerHub)
- `.github/compose.ci.yml` — override do Compose usado pelo job de integração
- `collections/` — coleções Postman por aula
- `.opencode/skills/` — skills de papéis (arquitetura-e-squad,
  engenharia-devops, especialista-ia)

## Convenções

- Python 3.12+ (Docker) / 3.14 (venv local); estilo Ruff; tipos via mypy.
- Sem comentários supérfluos; sem placeholders ansiosos; sem dead code.
- Segredos **somente** via `.env` (gitignored; `.env.example` documenta).
- IA: `LLM_PROVIDER=auto` é o padrão — Gemini preferencial e mock como
  fallback apenas para indisponibilidade técnica; `gemini` é estrito e `mock`
  é determinístico. Testes/CI fixam `LLM_PROVIDER=mock`; a `GEMINI_API_KEY`
  fica só no `.env` (nunca versione nem imprima a chave).
- CI/CD: a publicação no DockerHub usa os *repository secrets*
  `DOCKERHUB_USERNAME` e `DOCKERHUB_TOKEN`; nunca versione os valores.
- Toda decisão relevante fica registrada: specs, `README.md`,
  `docs/CHANGELOG.md` e `PROMPTS.md` (uso de IA).
- Contratos: eventos em `docs/contracts/` + `api/core/messaging/contracts.py`;
  HTTP em `docs/openapi.yaml` — atualize-os junto com o código.
- Rotas Django terminam em `/` (ex.: `/api/v1/assist/`).

## Validação obrigatória antes de entregar

1. `docker compose run --rm tests` verde (552+ testes, cobertura >= 85%).
2. `ruff check .` sem erros.
3. `mypy api services dashboard` verde (config em `pyproject.toml`, stubs em
   `requirements-dev.txt`; o CI roda o mesmo comando).
4. OpenAPI coerente com as rotas alteradas.
5. Ao mexer em Compose/CI: `docker compose up -d --build db api dashboard` +
   `python scripts/validar_compose.py` verdes.
