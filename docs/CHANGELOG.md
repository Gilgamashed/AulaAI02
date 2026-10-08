# Changelog

Todas as alterações relevantes do projeto SynapseShop. O formato segue o
[*Keep a Changelog*](https://keepachangelog.com/pt-BR/1.1.0/) e o versionamento
é [SemVer](https://semver.org/lang/pt-BR/). O ficheiro foi criado na Aula 13 e
codifica retroativamente o histórico das aulas anteriores.

## [1.13.0] - 2026-10-08 — Aula 13

> Documentação completa da API: contrato OpenAPI/Swagger, linter estático,
> interfaces interativas e artefactos de consumo para integradores externos.

### Adicionado

- **Contrato OpenAPI** (`docs/openapi.yaml`, OpenAPI 3.1): 18 paths, 31
  operações e 40 schemas, com títulos, descrições, tags, exemplos de pedido e
  resposta.
- **Esquema de erros padronizado** (`ErrorSchema`, RFC 7807 /
  `application/problem+json`) com extensões `code` e `errors` (validação por
  campo), incluindo os respostas `400/401/403/404/409/429/503`.
- **Convenções estandardizadas no contrato-alvo**: paginação
  (`page`/`limit`/`nextCursor`), filtros (`?status=`, `?category=`,
  `?canal=`, faixa de preço), ordenação (`sort=<campo>:<dir>` /
  `?ordering=`) e cabeçalhos obrigatórios (`Authorization`,
  `Idempotency-Key`, `X-Trace-Id`), com notas de implementação apontando o
  comportamento atual do DRF (`PAGE_SIZE=20`, `?ordering=`, `{detail}`).
- **Validação estática reproduzível**: `scripts/lint-openapi.ps1` (Spectral,
  `extends: spectral:oas`) — **0 erros e 0 avisos**; instala o CLI em
  `.spectral-tools/` sem tocar no repositório.
- **Documentação interativa servida pela aplicação**: Swagger UI em
  `/docs/` e ReDoc em `/redoc/` (ambos alimentados por `/docs/openapi.yaml`),
  a partir de `api/core/wiki_docs.py`.
- **Coleção Postman** (`collections/synapseshop_aula13.postman_collection.json`):
  41 requisições com exemplos de sucesso e erro anexados, cobrindo o contrato
  ponta a ponta.
- **Environment Postman** (`collections/synapseshop_aula13.postman_environment.json`)
  com variáveis globais (`base_url`, `inventory_url`, `token`, `trace_id`,
  `idempotency_key`).
- **`docs/CHANGELOG.md`** (este ficheiro) e **Checklist do Integrador
  Externo** no `README.md`.

### Alterado

- `README.md`: nova secção *Checklist do Integrador Externo (Aula 13)*.
- `PROMPTS.md`: históricos da Aula 13 (DoDs 1–3 e 4–9).
- `.gitignore`: `.spectral-tools/` e `node_modules/`.

### Notas

- O contrato-alvo documenta `limit`/`nextCursor`/`sort`/`X-Trace-Id`; a
  implementação atual devolve paginação DRF (`page`/`PAGE_SIZE=20`) e
  `?ordering=`. As diferenças estão sinalizadas como notas no próprio
  `openapi.yaml` e no Checklist do Integrador.
- Nenhuma dependência nova no Docker (`requirements*`, `Dockerfile`,
  `docker-compose.yml` intocados).

## [1.12.0] - 2026-10-XX — Aula 12

- Testes automatizados e cobertura (perfil `tests` do Compose), convenções da
  equipe e metas de cobertura.

## [1.11.0] - 2026-10-05 — Aula 11

- Segundo fluxo Kafka: **pagamento e notificação**. Endpoint de pagamento com
  idempotência ponta a ponta (OneToOne, `pagamento.registrados`),
  `Notificacao` com filtros e permissões por dono, DLQ própria e contrato
  `docs/contracts/pagamento_registrado.md`.

## [1.10.0] - 2026-10-XX — Aula 10

- Apache Kafka: partições, offsets e DLQ; reentrega por retenção de tópico
  (5/15/45 s), `acks=all` + produtor idempotente, medição de latência e
  vazão/paralelismo.

## [1.9.0] - 2026-10-XX — Aula 9

- Mensageria assíncrona: Kafka (padrão) e RabbitMQ (profile), contrato do
  evento `PedidoCriado`, idempotência em duas barreiras e recuo com DLQ.

## [1.8.0] - 2026-10-XX — Aula 8

- Cache-aside com Redis para listagens e detalhes do catálogo, métricas de
  hit rate (`GET /api/v1/cache/metrics/`) e modo degradado.

## [1.7.0] - 2026-10-XX — Aula 7

- Autenticação JWT (SimpleJWT), papéis admin/user (`IsAdminRole`),
  throttling (`anon` 20/min, `user` 100/min, `login` 5/min) e matriz de
  permissões.

## [1.6.0] - 2026-10-XX — Aula 6

- Modelagem relacional (User no Django; InventoryItem no FastAPI), índices,
  migrações com Alembic e camadas Repository + Service.

## [1.5.0] - 2026-10-XX — Aula 5

- Microsserviço de estoque (FastAPI) no Compose (`:8001`), CRUD em
  `/api/v1/inventory`.

## [1.4.0] - 2026-10-XX — Aula 4

- CRUD DRF de categorias e itens sob `/api/v1/` com o mesmo PostgreSQL.

## [1.0.0] – [1.3.0] — Aulas 1 a 3

- MVP do backend de pedidos, arquitetura em 6 camadas, Dockerfile multistage
  e orquestração com Docker Compose (7 serviços).