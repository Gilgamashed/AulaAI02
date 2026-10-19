# Testes automatizados e cobertura (Aula 12)

> Conteúdo extraído do README.md (registro da aula). O README mantém apenas o resumo e o link para aqui.

## Testes automatizados e cobertura (Aula 12)

A suíte roda em `pytest`, num container descartável, cobrindo as **duas**
aplicações do repositório ao mesmo tempo — a API Django (`api/core`) e o
microsserviço FastAPI (`services/inventory/app`) — num único runner, com um
único `pyproject.toml` na raiz.

### Como executar

```bash
# A forma da equipe: profile `tests` do compose (imagem Dockerfile.tests).
docker compose --profile tests run --rm tests
```

O serviço `tests` espera o `db` ficar saudável (o pytest-django cria e
destrói um banco `test_*` por execução), monta o diretório de trabalho por
cima da imagem — editar um teste **não** exige rebuild; só mudou um
`requirements*.txt`? Aí é preciso `docker compose build tests`.

Equivalente local, com o banco publicado (`docker compose up -d db`):

```bash
pytest --cov          # relatório + gate de cobertura no stdout
```

O relatório HTML sai em `htmlcov/index.html` depois de qualquer execução com
`--cov`.

### Estrutura

```
tests/
├── conftest.py                 # fixtures globais + mocks (isolamento)
├── unit/
│   ├── test_cache_utils.py         # utils críticos do cache-aside
│   ├── test_contracts_pedido.py    # contrato do evento PedidoCriado
│   ├── test_contracts_pagamento.py # contrato do PagamentoRegistrado
│   ├── test_erros.py               # relatório de erro dos consumidores
│   ├── test_notificacoes.py        # título/mensagem por método e canal
│   ├── test_inventory_service.py   # regras de negócio do estoque
│   └── test_inventory_repository.py# repositório real (SQLite em memória)
└── integration/
    ├── test_catalog_lifecycle.py   # POST/GET + efeito na base (pedra do DoD 4)
    ├── test_pedidos_pagamento_fluxo.py # idempotência e eventos via HTTP
    ├── test_auth_throttling.py     # 429 do login com cota baixa
    └── test_inventory_endpoints.py # rotas FastAPI com repositório falso
```

### Convenções da equipe

* **Markers.** Todo teste nasce marcado: `@pytest.mark.unit` ou
  `@pytest.mark.integration`. Markers desconhecidos são erro
  (`--strict-markers`), então um marker novo precisa entrar em
  `pyproject.toml`.
* **Isolamento é estrutural, não de disciplina.** O `tests/conftest.py` é o
  ponto único de isolamento e o `api/config/settings_test.py` torna-o
  garantia: nenhum teste toca Redis, Kafka ou RabbitMQ. As fixtures
  `autouse` zeram cache e métricas entre testes e substituem o broker por um
  duplo em memória — um 429 ou um contador não podem vazar de um teste para
  o outro.
* **Relógio fixo.** Testes que comparam payload/timestamp usam a fixture
  `relogio_fixo` (freezegun, `tick=False`); nada de asserção dependente da
  hora em que rodou.
* **Inventory sem banco.** Os testes HTTP do estoque trocam
  `get_inventory_service` pelo serviço sobre o repositório falso do conftest;
  a tabela `inventory_items` (governada pelo Alembic) **não** é tocada pela
  suíte. O repositório real é coberto em
  `tests/unit/test_inventory_repository.py` contra um SQLite em memória.
* **Throttling.** As cotas sobem para 1000/min no settings_test para a suíte
  não estourar por acidente; o 429 é provado de propósito em
  `tests/integration/test_auth_throttling.py`, que devolve a taxa do `login`
  para 1/min.
* **Determinismo no tempo:** nada de `sleep` nem de asserção dependente da
  passagem de tempo real — onde o tempo importa, congela-se o relógio.
* **Suíte determinística:** sem I/O externo aberto e sem paralelismo; um
  teste injeta a própria semente/estado quando precisar.

### Metas de cobertura

* **85% global** nas duas aplicações, com *enforcement*: o gate
  `--cov-fail-under=85` no `pyproject.toml` reprova a execução abaixo disso.
* **100% nos utilitários críticos**: `cache_metrics` e o relatório de erros
  são cobertos por `tests/unit`; os contratos `PedidoCriado`/
  `PagamentoRegistrado` também têm unit tests dedicados (`test_contracts_*`),
  embora estejam fora da métrica por morarem na infra de mensageria.
* O restante pode equilibrar: a meta é global, não por arquivo; um regresso
  grande num só serviço derruba o gate, um pequeno ajuste de scaffold não é
  motivo para "esconder" arquivo.
* **Escopo medido**: o `--cov` cobre as duas aplicações. Ficam de fora as
  superfícies que a suíte não exercita por construção — `migrations`, `__init__`,
  `tests`, `management/commands`, `admin`/`apps` (bootstrap do Django) e
  `api/core/messaging/*` (infra de broker que só roda em worker/CLI:
  `consumir_pedidos`, `republicar_pedidos`, `declarar_topicos_kafka`). A
  justificativa de cada exclusão está no `omit` do
  `[tool.coverage.run]` no `pyproject.toml`.

### Pendências técnicas registadas

O DoD 7 pede as pendências e melhorias da aula como *issues* no
[repositório](https://github.com/Gilgamashed/AulaAI02/issues) — todas foram
criadas via API do GitHub. As corrigidas nesta aula ficaram **fechadas**, com
um comentário a apontar a correção e o teste que a cobre; a única aberta
continua em backlog:

**Corrigidas nesta aula (fechadas):**

* [#1](https://github.com/Gilgamashed/AulaAI02/issues/1) — indentação de
  `get_itens_recentes` no `ItemDetalheSerializer` (`api/core/serializers.py`),
  causa do 500 no `GET /items/{id}/detalhes/`;
* [#2](https://github.com/Gilgamashed/AulaAI02/issues/2) — a fixture `item` do
  `conftest.py` passava um campo `stock` inexistente no model;
* [#3](https://github.com/Gilgamashed/AulaAI02/issues/3) — `httpx` como
  dependência explícita da suíte (TestClient do FastAPI) no
  `requirements-dev.txt`;
* [#4](https://github.com/Gilgamashed/AulaAI02/issues/4) — publicação com
  `transaction.on_commit` adiada no `TestCase` devolveria 503 prematuro; os
  testes de fluxo usam `@pytest.mark.django_db(transaction=True)`;
* [#5](https://github.com/Gilgamashed/AulaAI02/issues/5) — os testes de
  throttling do login precisavam de `db` (o `simplejwt` consulta a tabela de
  usuários mesmo com credencial inválida);
* [#6](https://github.com/Gilgamashed/AulaAI02/issues/6) — o override da cota
  do login não surtia efeito via `override_settings`; o fixture
  `throttling_baixo` patcha o atributo de classe `ThrottleMemoriaScope`;
* [#7](https://github.com/Gilgamashed/AulaAI02/issues/7) — a PK `BIGINT` não
  autoincrementa no SQLite; `_item()` passa `id` explícito.

**Aberta:**

* [#8](https://github.com/Gilgamashed/AulaAI02/issues/8) — no host, o
  `pytest --cov` local precisa do `DATABASE_URL` com as credenciais do `.env`
  do compose para o pytest-django criar o banco `test_*` — a via oficial da
  equipe é o container (`docker compose --profile tests ...`).

**Aula 14 (melhorias — abertas):**

* [#9](https://github.com/Gilgamashed/AulaAI02/issues/9) — adaptador HTTP do
  provedor de IA real (`LLM_BASE_URL`/`LLM_API_KEY`) cumprindo o contrato
  `ProvedorLlm`, com timeout no transporte e mapeamento 4xx/5xx;
* [#10](https://github.com/Gilgamashed/AulaAI02/issues/10) — agregação das
  métricas de `GET /api/v1/llm/metrics/` entre processos (Gunicorn/containers)
  e cortes por usuário/papel (hoje os contadores são do processo que atende);
* [#11](https://github.com/Gilgamashed/AulaAI02/issues/11) — guardrails
  adicionais no `POST /api/v1/assist`: sanização da saída, mitigação de
  prompt injection via logs e reforço de escopo dos modos `summarize`/`explain`;
* [#13](https://github.com/Gilgamashed/AulaAI02/issues/13) — expansão e revisão
  periódica dos padrões de redação de `api/core/llm/redacao.py` (CPF/CNPJ por
  dígito verificador, placa Mercosul, RG/CNH, chave PIX/IBAN) com regressão
  por padrão;
* [#14](https://github.com/Gilgamashed/AulaAI02/issues/14) — cache de respostas
  do assist (por `mode` + logs redigidos + parâmetros) com TTL e medição de
  hit rate/custo evitado.


