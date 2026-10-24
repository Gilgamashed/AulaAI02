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
docker compose run --rm dashboard python -m dashboard.simular_sqli  # simulação SQLi
python -m ruff check .                # lint
python -m mypy api services dashboard # verificação de tipos
python scripts/lint-openapi.ps1       # valida docs/openapi.yaml (Spectral)
```

## Estrutura

- `api/` — Django (app `core`, mensageria, LLM, commands, migrations)
- `services/inventory/` — FastAPI + SQLAlchemy/Alembic
- `dashboard/` — Streamlit (conexão segura, consultas parametrizadas, painel analítico)
- `tests/` — `unit/` e `integration/` (pytest + pytest-django)
- `specs/` — specs incrementais por aula (fonte de requisitos)
- `docs/` — autenticação, contratos de evento, OpenAPI, changelog, aulas
- `scripts/` — medições de cache/mensageria e lint do OpenAPI
- `collections/` — coleções Postman por aula
- `.opencode/skills/` — skills de papéis (arquitetura-e-squad,
  engenharia-devops, especialista-ia)

## Convenções

- Python 3.12+ (Docker) / 3.14 (venv local); estilo Ruff; tipos via mypy.
- Sem comentários supérfluos; sem placeholders ansiosos; sem dead code.
- Segredos **somente** via `.env` (gitignored; `.env.example` documenta).
- Toda decisão relevante fica registrada: specs, `README.md`,
  `docs/CHANGELOG.md` e `PROMPTS.md` (uso de IA).
- Contratos: eventos em `docs/contracts/` + `api/core/messaging/contracts.py`;
  HTTP em `docs/openapi.yaml` — atualize-os junto com o código.
- Rotas Django terminam em `/` (ex.: `/api/v1/assist/`).

## Validação obrigatória antes de entregar

1. `docker compose run --rm tests` verde (222+ testes, cobertura >= 85%).
2. `ruff check .` sem erros.
3. `mypy api services` sem novos erros.
4. OpenAPI coerente com as rotas alteradas.
