# Pipeline de CI/CD com GitHub Actions (Aula 22)

## Objetivo

Automatizar a verificação do SynapseShop a cada mudança: lint, suíte completa
de testes com cobertura e build da imagem Docker da API. O pipeline é a
primeira barreira contra regressões — e a prova de que o ambiente descrito no
README realmente constrói a partir de um clone limpo.

```
push / pull_request / workflow_dispatch
        │
        ├── test-and-lint ── ruff + pytest + cobertura 85% + artefatos
        │
        └── docker-build ─── docker build -t synapseshop-api:test .
```

As duas fases rodam em paralelo: o build da imagem não depende do resultado da
suíte, e vice-versa.

## Arquitetura do workflow

Arquivo: [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml).

### Gatilhos

| Evento | Branches |
| --- | --- |
| `push` | `main`, `master`, `dev` |
| `pull_request` | `main`, `master` |
| `workflow_dispatch` | qualquer branch selecionável na UI |

`dev` foi incluído além do que a spec pede porque é o branch de integração do
projeto: sem ele, nenhum commit diário seria verificado até a abertura de um
PR. O badge do README continua apontando para `main`.

### Job `test-and-lint`

| Etapa | Comando/ação |
| --- | --- |
| Checkout | `actions/checkout@v4` |
| Python | `actions/setup-python@v5`, versão `3.12` (a mesma da imagem de produção) |
| Dependências | `pip install -r requirements-dev.txt` |
| Lint | `python -m ruff check .` |
| Testes | `python -m pytest --junitxml=reports/junit.xml --cov-report=xml:reports/coverage.xml` |
| Relatórios | `actions/upload-artifact@v4` com `reports/` e `htmlcov/` (`if: always()`) |

O gate de cobertura não é reimplementado no YAML: ele já está em
`[tool.pytest.ini_options]` (`--cov-fail-under=85`). Um teste quebrado ou uma
queda de cobertura devolvem exit code diferente de zero e derrubam o job.

### PostgreSQL efêmero

O `pytest-django` cria e destrói um banco `test_*`, então o runner precisa de
um PostgreSQL de verdade. O workflow declara o serviço:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    env:
      POSTGRES_USER: synapse
      POSTGRES_PASSWORD: synapse
      POSTGRES_DB: synapse
    ports: ["5432:5432"]
    options: >-
      --health-cmd "pg_isready -U synapse -d synapse"
      --health-interval 5s
      --health-timeout 5s
      --health-retries 10
```

O job aponta `DATABASE_URL` para `localhost:5432` — o mesmo banco que o
`docker-compose.yml` oferece no host. As credenciais são descartáveis e não
são segredo: o serviço morre com o runner.

Nenhum outro serviço é necessário:

- **Redis** — `config.settings_test` troca os três aliases de cache por
  `LocMemCache`.
- **Kafka/RabbitMQ** — o `tests/conftest.py` substitui
  `publicar_pedido_criado` e `publicar_pagamento_registrado` por um duplo em
  memória (`autouse`), então nenhum teste publica em broker real.

### Job `docker-build`

| Etapa | Comando |
| --- | --- |
| Checkout | `actions/checkout@v4` |
| Build | `docker build --tag synapseshop-api:test .` |
| Confirmação | `docker image inspect synapseshop-api:test --format '{{.Id}}'` |

O `CMD` do Dockerfile roda migrações e gunicorn apenas em runtime; o build não
precisa de banco nem de `.env`. O `.dockerignore` já exclui `.git`, `.env`,
`htmlcov/` e outros artefatos, o que mantém o contexto enxuto e o cache de
camadas preservado.

## Variáveis e segredos

| Nome | Origem | Obrigatório? |
| --- | --- | --- |
| `DATABASE_URL` | definido no workflow | sim (banco do job) |
| `DJANGO_SECRET_KEY` | `secrets.DJANGO_SECRET_KEY` com fallback efêmero | não |
| `DJANGO_DEBUG` | fixo em `False` | não |
| `MENSAGERIA_BROKER` | fixo em `kafka` | não |
| `ASK_SQL_*` | fixos nos mesmos valores do Compose | não |

O `settings_test` sobrescreve `SECRET_KEY` e `JWT_SIGNING_KEY`, então a suíte
não depende de segredo cadastrado. O `secrets.DJANGO_SECRET_KEY` existe para
quem quiser exercitar o mesmo valor do ambiente real; se o secret não estiver
configurado, a expressão cai no valor `ci-insecure-synapseshop`.

Cadastro do segredo:

```bash
gh secret set DJANGO_SECRET_KEY --repo Gilgamashed/AulaAI02
```

Ou em **Settings → Secrets and variables → Actions → New repository secret**.
Segredos nunca entram no repositório nem no `.env.example`.

## Equivalente local

```bash
# Reconstrói a imagem de testes para instalar o ruff pinado
docker compose build tests

# Suíte completa + gate de cobertura
docker compose run --rm tests

# Lint dentro do mesmo ambiente do CI
docker compose run --rm tests python -m ruff check .

# Build da imagem da API
docker build -t synapseshop-api:test .
```

No host com venv:

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m pytest
```

## Evidências esperadas

- `ruff check .`: `All checks passed!`
- `pytest`: 398 testes verdes, cobertura global de 89,64% (baseline da Aula 21).
- `docker build`: imagem `synapseshop-api:test` criada sem erro.
- Artefatos `relatorios-testes`: `junit.xml`, `coverage.xml` e `htmlcov/`.

O número de testes pode crescer; o critério é suíte verde e cobertura
`>= 85%`.

## Limitações registradas

- **Sem CD:** o pipeline não publica imagem nem faz deploy. Isso é escopo da
  Aula 23.
- **Sem cache de dependências:** cada execução instala tudo do zero. Cache
  avançado também fica para a Aula 23.
- **Sem matrix:** roda apenas Python 3.12, a versão da imagem de produção. O
  venv local em 3.14 não é validado pelo CI.
- **Postgres efêmero:** o banco do job não tem as tabelas do Alembic
  (`inventory_items`); os testes do inventory usam repositório falso, por
  decisão da Aula 12.
