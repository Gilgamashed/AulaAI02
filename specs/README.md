# Specs — SpecDD do SynapseShop

Índice das especificações incrementais (metodologia SpecDD). Cada aula tem sua
spec; a implementação deve satisfazer apenas a spec da aula corrente (ver
`00_diretriz_incremental_specdd.md`).

## Meta-spec

- [00 — Diretriz de Desenvolvimento Incremental](00_diretriz_incremental_specdd.md)

## Specs por aula

| Aula | Spec |
|---|---|
| 1 | [Kick-off, Formação e Repositório](specs_da_aula_1.md) |
| 2 | [Esqueleto do Projeto e Conteinerização](specs_da_aula_2.md) |
| 3 | [Docker Essencial: Do Básico ao Compose](specs_da_aula_3.md) |
| 4 | [CRUD da API Principal com Django REST Framework](specs_da_aula_4.md) |
| 5 | [Microsserviço Complementar com FastAPI](specs_da_aula_5.md) |
| 6 | [Persistência do Inventário em PostgreSQL (SQLAlchemy/Alembic)](specs_da_aula_6.md) |
| 7 | [Autenticação JWT com papéis, throttling e filtros](specs_da_aula_7.md) |
| 8 | [Cache-Aside com Redis](specs_da_aula_8.md) |
| 9 | [Mensageria Assíncrona e Filas com RabbitMQ/Kafka](specs_da_aula_9.md) |
| 10 | [Mensageria Assíncrona com Apache Kafka, Idempotência e DLQ](specs_da_aula_10.md) |
| 11 | [Desafio Mão na Massa — Núcleo do Mini-Backend](specs_da_aula_11.md) |
| 12 | [Testes Automatizados e Cobertura](specs_da_aula_12.md) |
| 13 | [Documentação Completa da API com OpenAPI/Swagger e Postman](specs_da_aula_13.md) |
| 14 | [Assistente de IA e llm_service](specs_da_aula_14.md) |
| 15–16 | Sem spec própria — continuação do trabalho das aulas anteriores |
| 19 | [Conexão Segura, SQL Injection e Painel Streamlit](spec_da_aula_19.md) |
| 20 | [Dashboard de Desempenho da API em Streamlit](spec_da_aula_20.md) |
| 21 | [Consulta de Dados em Linguagem Natural (Texto-para-SQL)](spec_da_aula_21.md) |
| 22 | [Pipeline de CI/CD com GitHub Actions](spec_da_aula_22.md) |

## Relacionados

- Visão geral do curso (material do curso, não estado atual do produto):
  [`docs/curso/visao-geral.md`](../docs/curso/visao-geral.md)
- Contratos de evento: [`docs/contracts/`](../docs/contracts/)
- Contrato OpenAPI: [`docs/openapi.yaml`](../docs/openapi.yaml)
