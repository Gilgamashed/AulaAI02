# SynapseShop

Backend de Pedidos com Inteligência Artificial — MVP do projeto da squad.

## Equipe

> Lista provisória — atualizar conforme novos membros entrarem na squad.

| Integrante          | Papel                                            |
| ------------------- | ------------------------------------------------ |
| Caius I O           | Tech Lead / Product Owner / DevOps / SRE / Arquiteto / Desenvolvedor / Especialista em IA |

## Domínio

Loja de departamentos: catálogo de produtos variados, com pedidos gerados e
processados ponta a ponta.

## MVP — Backend de Pedidos com IA

O MVP consiste em um backend capaz de receber pedidos e processar o fluxo
**Pedido → Pagamento → Notificação**, com suporte de inteligência artificial
integrada. Nenhum framework web, banco de dados ou serviço externo é definido
nesta fase inicial; o desenvolvimento segue a metodologia **SpecDD** de forma
iterativa e incremental.

## Arquitetura-alvo (6 camadas)

1. **Clientes/Canais** — pontos de entrada que consomem o backend.
2. **Gateway de API e Autenticação** — DRF + FastAPI, com JWT e *throttling*.
3. **Serviços de Negócio** — `order`, `payment`, `inventory` e `notification`.
4. **Camada de IA** — serviços de inteligência artificial do backend de pedidos.
5. **Infraestrutura de Dados e Mensageria** — PostgreSQL, Redis, RabbitMQ/Kafka.
6. **Observabilidade, Qualidade e Entrega** — Streamlit, pytest, OpenAPI, CI/CD.

### Diagrama (versão inicial)

> Descrição textual provisória (a imagem oficial da arquitetura será adicionada
> quando disponível).

```
Clientes/Canais
      │
      v
Gateway de API + Autenticação (DRF + FastAPI, JWT, throttling)
      │
      v
Serviços de Negócio (order → payment → inventory → notification)
      │
      v
Camada de IA
      │
      v
Infraestrutura de Dados e Mensageria (PostgreSQL, Redis, RabbitMQ/Kafka)
      │
      v
Observabilidade | Qualidade | Entrega (Streamlit, pytest, OpenAPI, CI/CD)
```

## Stack de referência

Docker, Django REST Framework, FastAPI, PostgreSQL, SQLAlchemy, Alembic, Redis.

## Como subir o ambiente

Infraestrutura conteinerizada com Docker Compose (Aula 2/3, estendida até a
Aula 11). São **sete serviços**:

| Serviço      | Imagem             | Função                                               |
| ------------ | ------------------ | ---------------------------------------------------- |
| `api`        | build do Dockerfile | API Django REST Framework: `/health` + rotas CRUD em `/api/v1/` (porta 8000) |
| `db`         | `postgres:16-alpine` | Banco PostgreSQL (volume `pgdata` para persistência); porta interna `db:5432` **publicada em `localhost:5432`** para permitir comandos de gerenciamento locais (venv) |
| `redis`      | `redis:7-alpine`   | Cache-aside do microsserviço de estoque (Aula 8) **e** janela de dedupe dos dois fluxos Kafka (Aulas 9 a 11) |
| `kafka`      | Apache Kafka (KRaft, modo único nó) | Broker de mensageria. Roda com `auto.create.topics.enable=false`: quem cria os tópicos é a aplicação (ver "Subir o ambiente") |
| `inventory`  | build de `services/inventory/Dockerfile` | Microsserviço FastAPI de estoque: `/health`, `/docs` e CRUD em `/api/v1/inventory` (porta 8001); persistência própria no PostgreSQL governada pelo Alembic (Aula 6) |
| `worker-kafka` | mesma imagem da `api` | Consumidor do fluxo de **pedidos** (`pedidos.criados`, grupo `synapseshop-pedidos`) |
| `worker-pagamentos` | mesma imagem da `api` | Consumidor do fluxo de **pagamentos** (`pagamentos.registrados`, grupo `synapseshop-pagamentos`) |

Existe ainda um serviço `rabbitmq`, mas ele está atrás do profile `rabbitmq`
(Aulas 9/10) e **não sobe** no caminho Kafka — que é o broker padrão da Aula 11.
Para usá-lo: `docker compose --profile rabbitmq up -d`.

O `Dockerfile` usa **multistage build** (`builder` prepara as dependências;
`runtime` copia apenas o necessário) com cache eficiente de dependências e
execução via usuário não-root `appuser`. O serviço `api` só inicia depois que
o banco responde com sucesso ao `healthcheck` (`depends_on` +
`service_healthy`), e é o `api` quem aplica as migrações no startup (ver o
`CMD` do `Dockerfile`) — os dois workers esperam `api: service_healthy` para não
consumir antes das tabelas existirem.

### Pré-requisitos

- Docker Desktop (com WSL2) e Docker Compose.
- Arquivo `.env` na raiz com as credenciais do banco (usar `.env.example`
  como referência). O Compose o carrega automaticamente.

### Subir o ambiente

```bash
docker compose up -d --build
```

Não é preciso declarar os tópicos Kafka na mão: o broker sobe com
`auto.create.topics.enable=false`, então quem cria a topologia é a aplicação —
cada worker declara a topologia do **seu** fluxo antes de assinar o tópico
(`kafka_consumidor.py`, em `rodar()`), e o produtor a declara a cada publicação.
É isso que faz `docker compose up` bastar. O comando `declarar_topicos_kafka`
existe para **inspecionar** e para casos de recuperação, não como passo de
instalação.

O passo que **não** é opcional é o seed de usuários:

```bash
docker compose exec api python api/manage.py seed_auth
```

As migrations não criam usuários e o Compose não roda o seed. Sem este comando
**não existe `demo_user`**, e como todo endpoint de escrita exige JWT, o fluxo
pedido ➔ pagamento ➔ notificação fica impossível de exercitar. É idempotente:
pode repetir à vontade. As credenciais estão na seção
[Autenticação JWT](docs/autenticacao.md).

### Validar a disponibilidade

```bash
curl http://localhost:8000/health
# {"status": "ok", "service": "synapseshop-api", "broker": "kafka",
#  "fluxos": {"pedidos": {...}, "pagamentos": {...}}}

curl http://localhost:8001/health
# {"status": "ok", "service": "synapseshop-inventory"}
```

`fluxos` traz a **topologia** de cada fluxo (tópico, grupo, partições, retenção,
tópico de DLQ, escada de reentrega). Ele não traz `lag` nem contagem de DLQ de
propósito: o Compose usa `/health` como `healthcheck` do container, e ler os
watermarks a cada sondagem transformaria o endpoint de liveness em carga no
broker. Para o estado que se move:

```bash
docker compose exec api python api/manage.py declarar_topicos_kafka --fluxo pagamentos --json
docker compose exec api python api/manage.py inspecionar_dlq_kafka --fluxo pagamentos
```

### Acompanhar os logs

```bash
docker compose logs -f api          # logs do serviço API
docker compose logs -f db           # logs do PostgreSQL (ex.: "database system is ready")
docker compose logs -f inventory    # logs do microsserviço de estoque
docker compose logs -f worker-kafka       # consumo do fluxo de pedidos
docker compose logs -f worker-pagamentos  # consumo do fluxo de pagamentos
```

Os dois workers emitem **JSON**, e o campo `fluxo` distingue um do outro — o
mesmo `grep` serve para os dois:

```bash
docker compose logs worker-pagamentos | grep '"fluxo": "pagamentos"'
```

### Derrubar o ambiente

```bash
docker compose down             # encerra os containers (mantém o volume pgdata)
docker compose down -v          # encerra e apaga o volume (atenção: apaga os dados)
```

## Rotas da API (Aula 4)

A API principal usa **Django REST Framework** e expõe o CRUD de produtos
eletrônicos sob o prefixo versionado `/api/v1/`. As migrações são aplicadas
automaticamente no startup (o banco já está saudável via `depends_on`).

| Rota                           | Verbos                    | Descrição                                   |
| ------------------------------ | ------------------------- | ------------------------------------------- |
| `/health`                      | GET                       | Healthcheck da API (200)                    |
| `/api/v1/`                     | GET                       | Root do router (lista as rotas disponíveis) |
| `/api/v1/categories/`          | GET, POST                 | Listar / criar categorias                   |
| `/api/v1/categories/{id}/`     | GET, PUT, PATCH, DELETE   | Detalhe / atualizar / excluir categoria     |
| `/api/v1/items/`               | GET, POST                 | Listar / criar produtos eletrônicos         |
| `/api/v1/items/{id}/`          | GET, PUT, PATCH, DELETE   | Detalhe / atualizar / excluir produto       |

Status codes: **200** OK, **201** Created, **204** No Content, **400** Bad
Request, **404** Not Found. Validações customizadas: preço não-negativo, SKU no
formato `XXXX-AAAA-BBBB`, nomes de categoria/produto/marca/modelo não-vazios
(sem espaços em branco), `specifications` como objeto JSON e unicidade de
SKU/categoria.

> **Desde a Aula 7** essas rotas ganharam a camada de acesso: o **GET** (list/
> detail) permanece público e agora é paginado e filtrável; as escritas exigem
> **JWT** — **POST** aceita os papéis `user`/`admin`, enquanto **PUT/PATCH/
> DELETE** são restritos ao papel `admin`. Detalhes em
> [Autenticação JWT, papéis e throttling (Aula 7)](docs/autenticacao.md).


Coleção exportada para teste (importar no Postman e definir a variável
`base_url` como `http://localhost:8000`):
`collections/synapseshop_aula4.postman_collection.json`. Exemplos `curl` em
[docs/aulas/04-api.md](docs/aulas/04-api.md).

## Registro das aulas

O detalhamento técnico de cada aula foi movido para `docs/`; este README
mantém o estado atual do projeto e o índice para navegação.

| Aula | Tópico | Documento |
| ---- | ------ | --------- |
| 4 | CRUD da API com Django REST Framework | [docs/aulas/04-api.md](docs/aulas/04-api.md) |
| 5 | Microsserviço de estoque com FastAPI | [docs/aulas/05-inventory.md](docs/aulas/05-inventory.md) |
| 6 | Modelagem relacional, índices e migrações | [docs/aulas/06-modelagem.md](docs/aulas/06-modelagem.md) |
| 7 | Autenticação JWT, papéis e throttling | [docs/autenticacao.md](docs/autenticacao.md) |
| 8 | Cache-aside com Redis | [docs/aulas/08-cache.md](docs/aulas/08-cache.md) |
| 9 | Mensageria assíncrona (RabbitMQ) | [docs/aulas/09-mensageria.md](docs/aulas/09-mensageria.md) |
| 10 | Apache Kafka: partições, offsets e DLQ | [docs/aulas/10-kafka.md](docs/aulas/10-kafka.md) |
| 11 | Pagamento, notificação e segundo fluxo Kafka | [docs/aulas/11-pagamentos.md](docs/aulas/11-pagamentos.md) |
| 12 | Testes automatizados e cobertura | [docs/testes.md](docs/testes.md) |
| 13 | Checklist do Integrador Externo | [docs/integrador.md](docs/integrador.md) |
| 14 | Assistente de IA e llm_service | [docs/aulas/14-ia.md](docs/aulas/14-ia.md) |

## Documentação útil

- [Autenticação: tutorial operacional](docs/autenticacao.md) (login, usuários, admin)
- [Contrato OpenAPI](docs/openapi.yaml) — Swagger UI em `/docs/`, ReDoc em `/redoc/`
- [Contratos de evento](docs/contracts/)
- [Specs por aula (SpecDD)](specs/README.md)
- [Visão geral do curso](docs/curso/visao-geral.md)
- [PROMPTS.md](PROMPTS.md) — histórico de uso de IA (entrega obrigatória)

## Referências

- [Histórico de uso de IA generativa](PROMPTS.md)
- [Histórico de alterações](docs/CHANGELOG.md)
- [Diretriz SpecDD](specs/00_diretriz_incremental_specdd.md)
